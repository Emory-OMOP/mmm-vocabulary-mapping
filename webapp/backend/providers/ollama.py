"""Ollama provider using OpenAI-compatible API."""

import json
import logging
import uuid
from typing import AsyncIterator

import httpx

from .. import observability
from .base import AgentResponse, LLMProvider, ToolCall

logger = logging.getLogger(__name__)


def _to_openai_tools(tools: list[dict]) -> list[dict]:
    """Convert canonical tool schemas to OpenAI/Ollama format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        }
        for t in tools
    ]


def _convert_messages(messages: list[dict], system: str = "") -> list[dict]:
    """Convert messages to Ollama/OpenAI format, prepending system message.

    The agent loop stores messages in Claude format:
      - Assistant tool calls: {"role": "assistant", "content": [{"type": "tool_use", ...}]}
      - Tool results: {"role": "user", "content": [{"type": "tool_result", ...}]}
    This function converts both formats to Ollama's expected structure.
    """
    result = []
    if system:
        result.append({"role": "system", "content": system})

    for msg in messages:
        role = msg["role"]
        content = msg.get("content", "")

        # Handle Claude-format content blocks (list of dicts)
        if isinstance(content, list):
            # Check what types of blocks are in the content
            block_types = {b.get("type") for b in content if isinstance(b, dict)}

            if "tool_use" in block_types:
                # Assistant message with tool_use blocks → Ollama tool_calls
                # Ollama native format: no id, no type, arguments as dict
                text_parts = []
                tc_list = []
                for block in content:
                    if block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        tc_list.append({
                            "function": {
                                "name": block["name"],
                                "arguments": block.get("input", {}),
                            },
                        })
                msg_dict = {"role": "assistant", "content": "\n".join(text_parts)}
                if tc_list:
                    msg_dict["tool_calls"] = tc_list
                result.append(msg_dict)

            elif "tool_result" in block_types:
                # User message with tool_result blocks → Ollama tool responses
                # Ollama native format: just role + content, no tool_call_id
                for block in content:
                    if block.get("type") == "tool_result":
                        result.append({
                            "role": "tool",
                            "content": block.get("content", ""),
                        })
            else:
                # Unknown block types, serialize as text
                text = "\n".join(
                    b.get("text", str(b)) for b in content if isinstance(b, dict)
                )
                result.append({"role": role, "content": text})
        else:
            # Simple string content
            result.append({"role": role, "content": content})

    return result


def _parse_response(data: dict) -> AgentResponse:
    """Parse an Ollama /api/chat response into an AgentResponse."""
    message = data.get("message", {})
    text = message.get("content") or None
    tool_calls = []

    for tc in message.get("tool_calls", []):
        func = tc.get("function", {})
        args = func.get("arguments", {})
        if isinstance(args, str):
            args = json.loads(args)
        tool_calls.append(
            ToolCall(
                id=tc.get("id", str(uuid.uuid4())),
                name=func.get("name", ""),
                arguments=args,
            )
        )

    return AgentResponse(
        text=text,
        tool_calls=tool_calls,
        stop_reason="tool_calls" if tool_calls else "stop",
    )


class OllamaProvider(LLMProvider):
    """Ollama provider using the /api/chat endpoint with tool calling."""

    def __init__(
        self,
        model: str = "qwen2.5:14b",
        base_url: str = "http://localhost:11434",
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str = "",
        trace=None,
        temperature: float | None = None,
    ) -> AgentResponse:
        ollama_messages = _convert_messages(messages, system)
        ollama_tools = _to_openai_tools(tools) if tools else []

        payload = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": False,
        }
        if ollama_tools:
            payload["tools"] = ollama_tools
        if temperature is not None:
            payload["options"] = {"temperature": temperature}

        t0 = observability.timer()

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self.base_url}/api/chat",
                json=payload,
            )
            resp.raise_for_status()

        t1 = observability.timer()
        data = resp.json()
        result = _parse_response(data)

        # Record LLM generation in Langfuse
        token_usage = {}
        if "prompt_eval_count" in data:
            token_usage["input"] = data["prompt_eval_count"]
        if "eval_count" in data:
            token_usage["output"] = data["eval_count"]

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
            name="llm-ollama",
            model=self.model,
            input=messages[-1:],
            output=output_summary,
            usage=token_usage or None,
            metadata={
                "stop_reason": result.stop_reason,
                "latency_ms": round((t1 - t0) * 1000, 1),
                "local": True,
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
        ollama_messages = _convert_messages(messages, system)
        ollama_tools = _to_openai_tools(tools) if tools else []

        payload = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": True,
        }
        if ollama_tools:
            payload["tools"] = ollama_tools
        if temperature is not None:
            payload["options"] = {"temperature": temperature}

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json=payload,
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    msg = data.get("message", {})
                    if msg.get("content"):
                        yield msg["content"]
