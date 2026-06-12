"""OpenAI-compatible provider for OpenAI, Gemini, DeepSeek, and Kimi APIs.

All four services expose the OpenAI chat completions format with tool calling.
Uses its own strict message conversion (OpenAI requires id, type, tool_call_id,
and arguments as JSON strings) while sharing the tool schema conversion with Ollama.
"""

import json
import logging
import uuid
from typing import AsyncIterator

import httpx

from .. import observability
from .base import AgentResponse, LLMProvider, ToolCall
from .ollama import _to_openai_tools

logger = logging.getLogger(__name__)

# Endpoint configurations per provider
PROVIDER_ENDPOINTS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "chat_path": "/chat/completions",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "chat_path": "/chat/completions",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "chat_path": "/chat/completions",
    },
}


def _convert_messages_openai(messages: list[dict], system: str = "") -> list[dict]:
    """Convert Claude-format messages to strict OpenAI chat completions format.

    OpenAI requires: id + type on tool_calls, arguments as JSON string,
    and tool_call_id on tool-role messages.
    """
    result = []
    if system:
        result.append({"role": "system", "content": system})

    for msg in messages:
        role = msg["role"]
        content = msg.get("content", "")

        if isinstance(content, list):
            block_types = {b.get("type") for b in content if isinstance(b, dict)}

            if "tool_use" in block_types:
                text_parts = []
                tc_list = []
                for block in content:
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        args = block.get("input", {})
                        tc_list.append({
                            "id": block.get("id", str(uuid.uuid4())),
                            "type": "function",
                            "function": {
                                "name": block["name"],
                                "arguments": json.dumps(args) if isinstance(args, dict) else args,
                            },
                        })
                text = "\n".join(text_parts)
                msg_dict = {"role": "assistant", "content": text or None}
                if tc_list:
                    msg_dict["tool_calls"] = tc_list
                # Preserve reasoning_content for DeepSeek thinking mode
                if msg.get("reasoning_content"):
                    msg_dict["reasoning_content"] = msg["reasoning_content"]
                result.append(msg_dict)

            elif "tool_result" in block_types:
                for block in content:
                    if block.get("type") == "tool_result":
                        result.append({
                            "role": "tool",
                            "tool_call_id": block.get("tool_use_id", ""),
                            "content": block.get("content", ""),
                        })
            else:
                text = "\n".join(
                    b.get("text", str(b)) for b in content if isinstance(b, dict)
                )
                result.append({"role": role, "content": text})
        else:
            result.append({"role": role, "content": content})

    return result


def _parse_openai_response(data: dict) -> AgentResponse:
    """Parse an OpenAI-format chat completion response."""
    choices = data.get("choices", [])
    if not choices:
        return AgentResponse(text=None, tool_calls=[], stop_reason="error")

    message = choices[0].get("message", {})
    text = message.get("content") or None
    reasoning_content = message.get("reasoning_content") or None
    tool_calls = []

    for tc in message.get("tool_calls", []):
        func = tc.get("function", {})
        args = func.get("arguments", {})
        # Arguments may be a JSON string or dict depending on provider
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"raw": args}
        tool_calls.append(
            ToolCall(
                id=tc.get("id", str(uuid.uuid4())),
                name=func.get("name", ""),
                arguments=args,
            )
        )

    finish_reason = choices[0].get("finish_reason", "stop")
    return AgentResponse(
        text=text,
        tool_calls=tool_calls,
        stop_reason="tool_calls" if tool_calls else finish_reason,
        reasoning_content=reasoning_content,
    )


class OpenAICompatProvider(LLMProvider):
    """Provider for any OpenAI-compatible API (OpenAI, Gemini, DeepSeek, Kimi)."""

    def __init__(
        self,
        provider_name: str,
        model: str,
        api_key: str,
        timeout: float = 300.0,
    ):
        if provider_name not in PROVIDER_ENDPOINTS:
            raise ValueError(
                f"Unknown provider: {provider_name}. "
                f"Supported: {', '.join(PROVIDER_ENDPOINTS)}"
            )
        self.provider_name = provider_name
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

        endpoint = PROVIDER_ENDPOINTS[provider_name]
        self.chat_url = endpoint["base_url"] + endpoint["chat_path"]

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str = "",
        trace=None,
        temperature: float | None = None,
    ) -> AgentResponse:
        openai_messages = _convert_messages_openai(messages, system)
        openai_tools = _to_openai_tools(tools) if tools else []

        # DeepSeek thinking mode: "deepseek-reasoner" maps to deepseek-chat
        # with thinking enabled (reasoner model ID doesn't support tool calls)
        model_for_api = self.model
        if self.provider_name == "deepseek" and "reasoner" in self.model:
            model_for_api = "deepseek-chat"

        payload: dict = {
            "model": model_for_api,
            "messages": openai_messages,
        }
        if self.provider_name == "deepseek" and "reasoner" in self.model:
            payload["thinking"] = {"type": "enabled"}
        if openai_tools:
            payload["tools"] = openai_tools
        if temperature is not None:
            payload["temperature"] = temperature

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        t0 = observability.timer()

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                self.chat_url,
                json=payload,
                headers=headers,
            )
            if resp.status_code >= 400:
                logger.error(
                    "API error %s from %s: %s",
                    resp.status_code, self.provider_name, resp.text,
                )
            resp.raise_for_status()

        t1 = observability.timer()
        data = resp.json()
        result = _parse_openai_response(data)

        # Extract token usage if available
        usage = data.get("usage", {})
        token_usage = {}
        if usage.get("prompt_tokens"):
            token_usage["input"] = usage["prompt_tokens"]
        if usage.get("completion_tokens"):
            token_usage["output"] = usage["completion_tokens"]

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
            name=f"llm-{self.provider_name}",
            model=self.model,
            input=messages[-1:],
            output=output_summary,
            usage=token_usage or None,
            metadata={
                "stop_reason": result.stop_reason,
                "latency_ms": round((t1 - t0) * 1000, 1),
                "provider": self.provider_name,
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
        openai_messages = _convert_messages_openai(messages, system)
        openai_tools = _to_openai_tools(tools) if tools else []

        payload: dict = {
            "model": self.model,
            "messages": openai_messages,
            "stream": True,
        }
        if openai_tools:
            payload["tools"] = openai_tools
        if temperature is not None:
            payload["temperature"] = temperature

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST", self.chat_url, json=payload, headers=headers,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = data["choices"][0].get("delta", {})
                        if delta.get("content"):
                            yield delta["content"]
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
