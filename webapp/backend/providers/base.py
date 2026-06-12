"""Provider-agnostic LLM interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class ToolCall:
    """A tool call requested by the LLM."""
    id: str
    name: str
    arguments: dict


@dataclass
class AgentResponse:
    """Parsed response from any LLM provider."""
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"
    reasoning_content: str | None = None  # DeepSeek thinking mode CoT


class LLMProvider(ABC):
    """Abstract base class for LLM providers."""

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str = "",
        trace=None,
        temperature: float | None = None,
    ) -> AgentResponse:
        """Send messages and get a response, possibly with tool calls.

        Args:
            messages: Conversation history in provider-neutral format.
            tools: Tool schemas in canonical format (name, description, parameters).
            system: System prompt.
            trace: Langfuse trace/span for observability (None if disabled).
            temperature: Sampling temperature (None = provider default).

        Returns:
            AgentResponse with text and/or tool_calls.
        """
        ...

    @abstractmethod
    async def stream(
        self,
        messages: list[dict],
        tools: list[dict],
        system: str = "",
        trace=None,
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        """Stream a response as text chunks.

        Yields text deltas as they arrive. Tool calls are accumulated
        and yielded as a final JSON chunk.
        """
        ...
