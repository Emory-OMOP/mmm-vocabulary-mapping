"""Langfuse observability wrapper — the only module that imports langfuse.

Feature-flagged via LANGFUSE_ENABLED env var. When disabled (default),
all functions return None with zero overhead. Application code calls
these functions and handles None returns gracefully.

When enabled, Langfuse is **required** — any operation failure raises
LangfuseError so the caller can surface it and stop the experiment.
This prevents silent data loss during evaluation runs.

Written for Langfuse SDK v3 (OTEL-based). Key v3 changes from v2:
  - client.trace() is gone; use client.start_span() + span.update_trace()
  - parent.generation() is gone; use parent.start_observation(as_type='generation')
  - parent.span() is gone; use parent.start_span()
  - span.end() no longer accepts output/metadata; call span.update() first
  - usage dict key is now 'usage_details' (not 'usage')
"""
from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .config import Settings

logger = logging.getLogger(__name__)

_client = None  # Langfuse | None
_required = False  # True when Langfuse was enabled and initialized


class LangfuseError(Exception):
    """Raised when a required Langfuse operation fails.

    Only raised when LANGFUSE_ENABLED=true and the client was initialized.
    Callers should surface this as a fatal error that stops the experiment.
    """
    pass


def init(settings: Settings) -> None:
    """Initialize the Langfuse client if enabled.

    When LANGFUSE_ENABLED=true, initialization failure raises so the
    application refuses to start with a broken observability pipeline.
    """
    global _client, _required

    if not settings.langfuse_enabled:
        _required = False
        logger.info("Langfuse tracing disabled")
        return

    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        _required = True
        logger.info("Langfuse tracing enabled (required): %s", settings.langfuse_host)
    except ImportError:
        raise LangfuseError(
            "LANGFUSE_ENABLED=true but langfuse package not installed. "
            "Install it (uv add langfuse) or set LANGFUSE_ENABLED=false."
        )
    except Exception as e:
        raise LangfuseError(
            f"LANGFUSE_ENABLED=true but initialization failed: {e}"
        ) from e


def is_required() -> bool:
    """Return True if Langfuse is enabled and required for this session."""
    return _required


def shutdown() -> None:
    """Flush pending events and shut down the client."""
    if _client is not None:
        try:
            _client.flush()
        except Exception as e:
            logger.error("Langfuse shutdown error: %s", e)


def create_trace(
    name: str,
    user_id: str | None = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
):
    """Create a root span and set trace-level metadata.

    Returns the root LangfuseSpan (used as parent for child observations),
    or None if tracing is disabled.

    Raises LangfuseError if tracing is required and the operation fails.
    """
    if _client is None:
        return None

    try:
        root = _client.start_span(name=name)

        # Set trace-level metadata via the root span
        trace_kwargs: dict[str, Any] = {"name": name}
        if user_id:
            trace_kwargs["user_id"] = user_id
        if session_id:
            trace_kwargs["session_id"] = session_id
        if metadata:
            trace_kwargs["metadata"] = metadata
        if tags:
            trace_kwargs["tags"] = tags

        root.update_trace(**trace_kwargs)
        return root
    except Exception as e:
        raise LangfuseError(f"create_trace failed: {e}") from e


def create_generation(
    parent,
    name: str,
    model: str,
    input: Any = None,
    output: Any = None,
    usage: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
):
    """Create a generation (LLM call) under a trace/span. Fire-and-forget.

    Returns None if parent is None (tracing disabled).
    The generation is created with all data and ended immediately.

    Raises LangfuseError if tracing is required and the operation fails.
    """
    if parent is None:
        return None

    try:
        kwargs: dict[str, Any] = {
            "name": name,
            "as_type": "generation",
            "model": model,
        }
        if input is not None:
            kwargs["input"] = input
        if output is not None:
            kwargs["output"] = output
        if usage:
            kwargs["usage_details"] = usage
        if metadata:
            kwargs["metadata"] = metadata

        gen = parent.start_observation(**kwargs)
        gen.end()
        return gen
    except Exception as e:
        raise LangfuseError(f"create_generation failed: {e}") from e


def create_span(
    parent,
    name: str,
    input: Any = None,
    metadata: dict[str, Any] | None = None,
):
    """Create a span (tool call, etc.) under a trace or span.

    Returns None if parent is None (tracing disabled).
    Caller must call span.update(output=...) then span.end() when done.

    Raises LangfuseError if tracing is required and the operation fails.
    """
    if parent is None:
        return None

    try:
        kwargs: dict[str, Any] = {"name": name}
        if input is not None:
            kwargs["input"] = input
        if metadata:
            kwargs["metadata"] = metadata

        return parent.start_span(**kwargs)
    except Exception as e:
        raise LangfuseError(f"create_span failed: {e}") from e


def end_trace(trace, output: Any = None, metadata: dict[str, Any] | None = None) -> None:
    """Finalize the root span, update trace output, and flush.

    Call when the request is done. Flushes after every trace to prevent
    events accumulating in the buffer during long-running evaluation runs.

    Raises LangfuseError if tracing is required and the operation fails.
    """
    if trace is None:
        return

    try:
        if metadata:
            trace.update(metadata=metadata)
        if output is not None:
            trace.update_trace(output=output)
        trace.end()
    except Exception as e:
        raise LangfuseError(f"end_trace failed: {e}") from e

    # Flush after every trace to ensure data is persisted
    if _client is not None:
        try:
            _client.flush()
        except Exception as e:
            raise LangfuseError(f"flush failed: {e}") from e


def timer() -> float:
    """Return current monotonic time for latency measurement."""
    return time.monotonic()
