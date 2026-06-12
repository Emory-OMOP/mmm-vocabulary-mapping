"""Agent loop: runs the LLM tool_use cycle and yields SSE events."""

import json
import logging
from dataclasses import dataclass
from typing import AsyncIterator

from . import observability
from .mcp_client import execute_tool, get_resource_content, get_tool_schemas
from .observability import LangfuseError
from .providers.base import LLMProvider, ToolCall

logger = logging.getLogger(__name__)

from .config import settings

MAX_TOOL_ROUNDS = settings.max_tool_rounds


@dataclass
class SSEEvent:
    """A server-sent event for streaming to the frontend."""
    event: str  # "text", "tool_call", "tool_result", "error", "done"
    data: str

    def encode(self) -> str:
        """Encode as SSE wire format."""
        return f"event: {self.event}\ndata: {self.data}\n\n"


def _build_tool_call_message(
    tool_calls: list[ToolCall],
    reasoning_content: str | None = None,
) -> dict:
    """Build an assistant message containing tool_use blocks (Claude format)."""
    content = []
    for tc in tool_calls:
        content.append({
            "type": "tool_use",
            "id": tc.id,
            "name": tc.name,
            "input": tc.arguments,
        })
    msg = {"role": "assistant", "content": content}
    # Preserve DeepSeek thinking mode reasoning for round-tripping
    if reasoning_content:
        msg["reasoning_content"] = reasoning_content
    return msg


def _build_tool_result_message(tool_call_id: str, result: str) -> dict:
    """Build a user message containing a tool_result block (Claude format)."""
    return {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": tool_call_id,
                "content": result,
            }
        ],
    }


async def agent_loop(
    provider: LLMProvider,
    messages: list[dict],
    system_prompt: str = "",
    trace=None,
    temperature: float | None = None,
    allow_raw_sql: bool | None = None,
) -> AsyncIterator[SSEEvent]:
    """Run the agent tool_use loop, yielding SSE events.

    The loop:
    1. Send messages to the LLM
    2. If LLM returns text, yield it
    3. If LLM returns tool_calls, execute each tool and append results
    4. Repeat until no more tool_calls or max rounds reached
    """
    tools = get_tool_schemas(allow_raw_sql=allow_raw_sql)
    rounds = 0
    total_tool_calls = 0

    # Inject MCP resource content into the system prompt (once, before loop)
    try:
        resource_content = await get_resource_content()
        if resource_content:
            system_prompt = f"{system_prompt}\n\n{resource_content}" if system_prompt else resource_content
    except Exception as e:
        logger.debug("Resource injection skipped: %s", e)

    while rounds < MAX_TOOL_ROUNDS:
        rounds += 1

        try:
            response = await provider.chat(messages, tools, system_prompt, trace=trace, temperature=temperature)
        except LangfuseError:
            raise  # Fatal — let main.py surface this through SSE
        except Exception as e:
            logger.error("LLM call failed: %s", e)
            yield SSEEvent(event="error", data=json.dumps({"error": str(e)}))
            break

        # Yield any text content
        if response.text:
            yield SSEEvent(event="text", data=json.dumps({"text": response.text}))

        # If no tool calls, we're done
        if not response.tool_calls:
            break

        # Build the assistant message with tool_use blocks
        assistant_msg = _build_tool_call_message(
            response.tool_calls,
            reasoning_content=response.reasoning_content,
        )

        # If there was also text, prepend it
        if response.text:
            assistant_msg["content"].insert(0, {"type": "text", "text": response.text})

        messages.append(assistant_msg)

        # Execute each tool call and collect results
        tool_results = []
        for tc in response.tool_calls:
            total_tool_calls += 1
            yield SSEEvent(
                event="tool_call",
                data=json.dumps({"id": tc.id, "name": tc.name, "arguments": tc.arguments}),
            )

            # Wrap tool execution in a Langfuse span
            span = observability.create_span(
                trace, name=f"tool:{tc.name}", input=tc.arguments,
            )
            t0 = observability.timer()

            result = await execute_tool(tc.name, tc.arguments)

            if span:
                latency_ms = (observability.timer() - t0) * 1000
                span.update(
                    output=result[:2000],
                    metadata={"latency_ms": round(latency_ms, 1)},
                )
                span.end()

            yield SSEEvent(
                event="tool_result",
                data=json.dumps({"id": tc.id, "name": tc.name, "result": result}),
            )

            tool_results.append((tc.id, result))

        # Append all tool results as a single user message with multiple tool_result blocks
        result_content = []
        for tc_id, result in tool_results:
            result_content.append({
                "type": "tool_result",
                "tool_use_id": tc_id,
                "content": result,
            })
        messages.append({"role": "user", "content": result_content})

    if rounds >= MAX_TOOL_ROUNDS:
        yield SSEEvent(
            event="error",
            data=json.dumps({"error": "Maximum tool rounds reached"}),
        )

    # Update root span with summary metadata
    if trace:
        trace.update(metadata={
            "total_rounds": rounds,
            "total_tool_calls": total_tool_calls,
        })
        # Note: trace.end() is called by observability.end_trace() in main.py

    yield SSEEvent(event="done", data=json.dumps({"rounds": rounds}))
