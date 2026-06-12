"""FastAPI application: routes, CORS, lifespan."""

import json
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .agent import agent_loop
from .auth import create_token, require_auth, validate_passkey
from .config import settings
from . import mcp_client, observability
from .observability import LangfuseError
from .models import (
    ChatRequest,
    HealthResponse,
    LoginRequest,
    LoginResponse,
)
from .providers import ClaudeProvider, OllamaProvider, OpenAICompatProvider
from .session import (
    add_message,
    create_session,
    get_messages,
    list_sessions,
    update_session_title,
)

logger = logging.getLogger(__name__)

# Appended to system prompt only for web chat requests (not MCP/CLI callers)
_VIZ_SUPPLEMENT = (
    "\n\n## Visualization\n"
    "When query results are tabular with labels and numeric values, render a chart "
    "by emitting a fenced code block tagged `viz` with a JSON object:\n"
    "```viz\n"
    '{"type": "bar", "title": "Top 5 Conditions", '
    '"labels": ["T2DM", "HTN", "HF", "CKD", "COPD"], '
    '"values": [12340, 9870, 6540, 4320, 3210]}\n'
    "```\n"
    "Fields: type (bar|line|pie|doughnut), title (string), labels (string array), "
    "values (number array — one per label).\n"
    "Place the viz block after your text explanation. "
    "Only visualize when the data has clear categories and numeric values."
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown."""
    logger.info("Starting OHDSI Agent webapp")
    logger.info("Default provider: %s/%s", settings.default_provider, settings.default_model)
    observability.init(settings)
    await mcp_client.connect(settings)
    yield
    await mcp_client.disconnect()
    observability.shutdown()
    logger.info("Shutting down OHDSI Agent webapp")


app = FastAPI(
    title="OHDSI Agent API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Provider factory ───────────────────────────────────────────────────────

_OPENAI_COMPAT_PROVIDERS = {
    "openai": "openai_api_key",
    "gemini": "gemini_api_key",
    "deepseek": "deepseek_api_key",
}


def _get_provider(provider_name: str | None = None, model: str | None = None):
    """Create an LLM provider instance."""
    name = provider_name or settings.default_provider
    mdl = model or settings.default_model

    if name == "claude":
        return ClaudeProvider(model=mdl, api_key=settings.anthropic_api_key)
    elif name == "ollama":
        return OllamaProvider(model=mdl, base_url=settings.ollama_base_url)
    elif name in _OPENAI_COMPAT_PROVIDERS:
        api_key = getattr(settings, _OPENAI_COMPAT_PROVIDERS[name])
        return OpenAICompatProvider(
            provider_name=name, model=mdl, api_key=api_key,
        )
    else:
        raise ValueError(f"Unknown provider: {name}")


# ── Auth routes ────────────────────────────────────────────────────────────

@app.post("/api/auth/login", response_model=LoginResponse)
async def login(req: LoginRequest):
    """Validate passkey and return JWT."""
    if not validate_passkey(req.passkey):
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Invalid passkey")

    token = create_token()
    return LoginResponse(token=token, expires_in_days=settings.jwt_expiry_days)


# ── Chat routes ────────────────────────────────────────────────────────────

@app.post("/api/chat")
async def chat(req: ChatRequest, _user: dict = Depends(require_auth)):
    """Send a message to the agent. Returns SSE stream."""
    provider = _get_provider(req.provider, req.model)
    provider_name = req.provider or settings.default_provider
    model_name = req.model or settings.default_model

    # Create or reuse session
    if req.session_id:
        session_id = req.session_id
        # Load existing messages
        existing = get_messages(session_id)
        messages = [
            {"role": m["role"], "content": m["content"]}
            for m in existing
            if m["role"] in ("user", "assistant")
        ]
    else:
        session_id = create_session(provider_name, model_name)
        messages = []

    # Save the user message
    add_message(session_id, "user", req.message)
    messages.append({"role": "user", "content": req.message})

    # Create Langfuse trace for this request
    trace = None
    try:
        trace = observability.create_trace(
            name="chat",
            user_id=_user.get("sub", "anonymous"),
            session_id=session_id,
            metadata={"provider": provider_name, "model": model_name, "temperature": req.temperature},
            tags=["webapp", provider_name, model_name],
        )
    except LangfuseError as e:
        logger.error("Langfuse trace creation failed: %s", e)

        async def error_stream():
            yield f"event: error\ndata: {json.dumps({'error': f'langfuse: {e}'})}\n\n"
            yield f"event: done\ndata: {json.dumps({'rounds': 0})}\n\n"
            yield f"event: session\ndata: {json.dumps({'session_id': session_id})}\n\n"

        return StreamingResponse(
            error_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Session-Id": session_id},
        )

    async def event_stream():
        """Generate SSE events from the agent loop."""
        full_response_text = []

        # Per-request allow_raw_sql: explicit request value, else server default
        effective_raw_sql = (
            req.allow_raw_sql if req.allow_raw_sql is not None
            else settings.allow_raw_sql
        )

        try:
            async for event in agent_loop(
                provider, messages, settings.system_prompt + _VIZ_SUPPLEMENT,
                trace=trace,
                temperature=req.temperature,
                allow_raw_sql=effective_raw_sql,
            ):
                yield event.encode()

                # Collect text for saving
                if event.event == "text":
                    data = json.loads(event.data)
                    if data.get("text"):
                        full_response_text.append(data["text"])
        except LangfuseError as e:
            logger.error("Langfuse error during agent loop: %s", e)
            yield f"event: error\ndata: {json.dumps({'error': f'langfuse: {e}'})}\n\n"

        # Save the assistant response
        combined = None
        if full_response_text:
            combined = "\n".join(full_response_text)
            add_message(session_id, "assistant", combined)

            # Auto-title the session from the first exchange
            if not req.session_id:
                title = req.message[:80]
                update_session_title(session_id, title)

        # Finalize the trace — if this fails, surface through SSE
        try:
            observability.end_trace(trace, output=(combined[:2000] if combined else None))
        except LangfuseError as e:
            logger.error("Langfuse end_trace failed: %s", e)
            yield f"event: error\ndata: {json.dumps({'error': f'langfuse: {e}'})}\n\n"

        # Final event with session_id
        yield f"event: session\ndata: {json.dumps({'session_id': session_id})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Session-Id": session_id,
        },
    )


@app.get("/api/chat/{session_id}/history")
async def chat_history(session_id: str, _user: dict = Depends(require_auth)):
    """Get chat history for a session."""
    messages = get_messages(session_id)
    return {"session_id": session_id, "messages": messages}


# ── Session routes ─────────────────────────────────────────────────────────

@app.get("/api/sessions")
async def sessions_list(_user: dict = Depends(require_auth)):
    """List chat sessions."""
    sessions = list_sessions()
    return {"sessions": sessions}


# ── Concept search (direct, no agent) ─────────────────────────────────────

@app.get("/api/concepts/search")
async def concepts_search(
    keyword: str = Query(..., min_length=1),
    domain: str | None = None,
    vocabulary_id: str | None = None,
    concept_class: str | None = None,
    standard_only: bool = True,
    limit: int = Query(25, ge=1, le=50),
    _user: dict = Depends(require_auth),
):
    """Direct concept search without going through the agent."""
    result = await mcp_client.execute_tool("search_concepts", {
        "keyword": keyword,
        "domain": domain,
        "vocabulary_id": vocabulary_id,
        "concept_class": concept_class,
        "standard_only": standard_only,
        "limit": limit,
    })
    return json.loads(result)


# ── Health check ───────────────────────────────────────────────────────────

@app.get("/api/health", response_model=HealthResponse)
async def health():
    """Health check — no auth required."""
    return HealthResponse(
        status="ok",
        version="0.1.0",
        mcp_servers=len(mcp_client._clients),
        mcp_tools=len(mcp_client._tool_schemas),
    )
