"""Pydantic request/response schemas for the API."""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    passkey: str


class LoginResponse(BaseModel):
    token: str
    expires_in_days: int = 30


class ChatMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant|system)$")
    content: str


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    provider: str | None = None
    model: str | None = None
    temperature: float | None = None
    allow_raw_sql: bool | None = None  # per-request override; None → use server default


class SessionInfo(BaseModel):
    id: str
    created_at: str
    title: str | None = None
    provider: str
    model: str
    message_count: int = 0


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
    mcp_servers: int = 0
    mcp_tools: int = 0


class ConceptSearchRequest(BaseModel):
    keyword: str
    domain: str | None = None
    vocabulary_id: str | None = None
    concept_class: str | None = None
    standard_only: bool = True
    limit: int = 25
