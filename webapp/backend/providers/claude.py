"""Anthropic Claude API provider."""

import json
import logging
from typing import AsyncIterator

import anthropic
import httpx

from .. import observability
from .base import AgentResponse, LLMProvider, ToolCall

logger = logging.getLogger(__name__)


def _to_claude_tools(tools: list[dict]) -> list[dict]:
    """Convert canonical tool schemas to Claude's format. Caches the whole
    tools block via cache_control on the LAST tool (Anthropic treats that
    as a cache breakpoint covering everything up to and including it).
    """
    out = [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["parameters"],
        }
        for t in tools
    ]
    if out:
        out[-1] = {**out[-1], "cache_control": {"type": "ephemeral"}}
    return out


def _to_cached_system(system: str) -> list[dict]:
    """Wrap the system prompt as a single cached content block."""
    return [
        {
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},
        }
    ]


def _parse_response(response) -> AgentResponse:
    """Parse a Claude API response into an AgentResponse."""
    text_parts = []
    tool_calls = []

    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append(
                ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input,
                )
            )

    return AgentResponse(
        text="\n".join(text_parts) if text_parts else None,
        tool_calls=tool_calls,
        stop_reason=response.stop_reason or "end_turn",
    )


class ClaudeProvider(LLMProvider):
    """Anthropic Claude API provider with tool_use support."""

    def __init__(self, model: str = "claude-sonnet-4-20250514", api_key: str = ""):
        self.client = anthropic.AsyncAnthropic(
            api_key=api_key or None,
            timeout=httpx.Timeout(180.0, connect=10.0),
            max_retries=2,
        )
        self.model = model

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str = "",
        trace=None,
        temperature: float | None = None,
    ) -> AgentResponse:
        claude_tools = _to_claude_tools(tools)

        kwargs = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 4096,
        }
        if claude_tools:
            kwargs["tools"] = claude_tools
        if system:
            kwargs["system"] = _to_cached_system(system)
        if temperature is not None:
            kwargs["temperature"] = temperature

        t0 = observability.timer()
        response = await self.client.messages.create(**kwargs)
        t1 = observability.timer()

        result = _parse_response(response)

        # Record LLM generation in Langfuse
        usage = getattr(response, "usage", None)
        if usage:
            token_usage = {
                "input": usage.input_tokens,
                "output": usage.output_tokens,
            }
            cache_create = getattr(usage, "cache_creation_input_tokens", 0) or 0
            cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
            if cache_create or cache_read:
                token_usage["cache_creation_input_tokens"] = cache_create
                token_usage["cache_read_input_tokens"] = cache_read
        else:
            token_usage = None

        output_summary = {}
        if result.text:
            output_summary["text"] = result.text[:500]
        if result.tool_calls:
            output_summary["tool_calls"] = [
                {"name": tc.name, "arguments": tc.arguments}
                for tc in result.tool_calls
            ]

        observability.create_generation(
            parent=trace,
            name="llm-claude",
            model=self.model,
            input=messages[-1:],
            output=output_summary,
            usage=token_usage,
            metadata={
                "stop_reason": result.stop_reason,
                "latency_ms": round((t1 - t0) * 1000, 1),
            },
        )

        return result

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str = "",
        trace=None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        claude_tools = _to_claude_tools(tools)

        kwargs = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 4096,
        }
        if claude_tools:
            kwargs["tools"] = claude_tools
        if system:
            kwargs["system"] = _to_cached_system(system)
        if temperature is not None:
            kwargs["temperature"] = temperature

        async with self.client.messages.stream(**kwargs) as stream:
            async for event in stream:
                if hasattr(event, "type"):
                    if event.type == "content_block_delta":
                        if hasattr(event.delta, "text"):
                            yield event.delta.text
                        elif hasattr(event.delta, "partial_json"):
                            yield json.dumps({"partial_tool_input": event.delta.partial_json})
