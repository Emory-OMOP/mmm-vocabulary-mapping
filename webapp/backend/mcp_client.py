"""MCP client layer — connects to all MCP servers over streamable-http.

Replaces tools.py. Instead of importing core functions directly, this
module connects to MCP servers as a client and dispatches tool calls
via the MCP protocol. Tool schemas are discovered dynamically.

Public interface (same as the old tools.py):
    connect(settings)       — called during app lifespan startup
    disconnect()            — called during app lifespan shutdown
    get_tool_schemas()      — returns merged schemas from all servers
    execute_tool(name, args) — routes to correct server, returns result string
"""
from __future__ import annotations

import json
import logging
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING, Any

from fastmcp import Client

if TYPE_CHECKING:
    from .config import Settings

logger = logging.getLogger(__name__)

# Exception class names that indicate a broken connection worth retrying.
_CONNECTION_ERROR_NAMES = frozenset({
    "ReadTimeout", "ConnectTimeout", "ConnectError", "RemoteProtocolError",
    "ClosedResourceError", "EndOfStream", "BrokenResourceError",
})

# Module-level state (same pattern as observability.py)
_stack: AsyncExitStack | None = None
_clients: dict[str, Client] = {}       # server_name -> connected client
_server_urls: dict[str, str] = {}      # server_name -> url (for reconnection)
_tool_to_server: dict[str, str] = {}   # tool_name -> server_name
_tool_schemas: list[dict] = []         # canonical format for providers
_resources: list[dict] = []            # discovered MCP resources
_resource_cache: str | None = None     # cached result of get_resource_content()


def _is_connection_error(exc: Exception) -> bool:
    """Check if an exception indicates a broken MCP connection."""
    return (
        type(exc).__name__ in _CONNECTION_ERROR_NAMES
        or isinstance(exc, (ConnectionError, OSError))
    )


def _make_client(url: str) -> Client:
    """Create an MCP client for a streamable-http URL."""
    return Client(url)


async def _connect_server(name: str, url: str) -> list[dict]:
    """Connect a single MCP server and discover its tools/resources.

    Returns the list of tool schemas discovered from this server.
    """
    client = _make_client(url)
    connected = await _stack.enter_async_context(client)
    _clients[name] = connected

    # Discover tools
    schemas: list[dict] = []
    tools = await connected.list_tools()
    for tool in tools:
        _tool_to_server[tool.name] = name
        schemas.append({
            "name": tool.name,
            "description": tool.description or "",
            "parameters": tool.inputSchema,
        })

    # Discover resources
    try:
        resources = await connected.list_resources()
        for res in resources:
            uri = str(res.uri) if hasattr(res, "uri") else str(res)
            res_name = res.name if hasattr(res, "name") else uri
            _resources.append({
                "uri": uri,
                "name": res_name,
                "server": name,
            })
        logger.info(
            "MCP server %s: discovered %d resources",
            name, len(resources),
        )
    except Exception as re:
        logger.debug(
            "MCP server %s: resource discovery skipped: %s", name, re,
        )

    logger.info(
        "MCP server %s: connected (%d tools) at %s",
        name, len(tools), url,
    )
    return schemas


async def _reconnect_server(name: str) -> bool:
    """Reconnect a single MCP server after connection failure.

    Returns True if reconnection succeeded.
    """
    global _tool_schemas

    url = _server_urls.get(name)
    if not url or not _stack:
        return False

    logger.info("Reconnecting to MCP server %s at %s ...", name, url)

    # Remove stale state for this server
    stale_tools = {t for t, s in _tool_to_server.items() if s == name}
    for t in stale_tools:
        del _tool_to_server[t]
    _tool_schemas = [s for s in _tool_schemas if s["name"] not in stale_tools]
    _clients.pop(name, None)
    # Note: stale resources are harmless (read_resource will fail gracefully)

    try:
        new_schemas = await _connect_server(name, url)
        _tool_schemas.extend(new_schemas)
        return True
    except Exception as e:
        logger.error("Failed to reconnect to MCP server %s: %s", name, e)
        return False


async def connect(settings: Settings) -> None:
    """Connect to all configured MCP servers. Call during app startup."""
    global _stack, _clients, _tool_to_server, _tool_schemas

    _stack = AsyncExitStack()
    await _stack.__aenter__()

    # This extract ships the two MCP servers the winning MMM run used:
    # ohdsi-vocab (Layer 1 retrieval/grounding) and omcp (read-only OMOP SQL —
    # Select_Query / Get_Information_Schema). The full Emory agent additionally
    # wired up circe-compiler, omop-sidecar, and concept-set-constructor; those
    # are out of scope for the vocabulary-mapping path and are not included.
    servers = {
        "ohdsi-vocab": settings.mcp_ohdsi_vocab_url,
        "omcp": settings.mcp_omcp_url,
    }

    all_schemas: list[dict] = []

    for name, url in servers.items():
        if not url:
            logger.info("MCP server %s: skipped (no URL configured)", name)
            continue

        _server_urls[name] = url

        try:
            schemas = await _connect_server(name, url)
            all_schemas.extend(schemas)
        except Exception as e:
            logger.error("MCP server %s: failed to connect at %s: %s", name, url, e)

    _tool_schemas = all_schemas
    logger.info(
        "MCP client ready: %d servers, %d tools",
        len(_clients), len(_tool_schemas),
    )


async def disconnect() -> None:
    """Disconnect from all MCP servers. Call during app shutdown."""
    global _stack, _clients, _tool_to_server, _tool_schemas, _resource_cache

    if _stack is not None:
        try:
            await _stack.aclose()
        except Exception as e:
            logger.error("MCP client shutdown error: %s", e)

    _stack = None
    _clients.clear()
    _server_urls.clear()
    _tool_to_server.clear()
    _tool_schemas.clear()
    _resources.clear()
    _resource_cache = None
    logger.info("MCP clients disconnected")


_RAW_SQL_TOOLS = frozenset({"Select_Query", "Get_Information_Schema"})


def get_tool_schemas(allow_raw_sql: bool | None = None) -> list[dict]:
    """Return all tool schemas in canonical format (name, description, parameters).

    When allow_raw_sql is False, Select_Query and Get_Information_Schema
    are filtered out to prevent the LLM from bypassing the CIRCE compilation
    pipeline for cohort queries.

    Args:
        allow_raw_sql: Per-request override. None falls back to settings.allow_raw_sql.
    """
    if allow_raw_sql is None:
        from .config import settings
        allow_raw_sql = settings.allow_raw_sql

    if allow_raw_sql:
        return _tool_schemas
    return [s for s in _tool_schemas if s["name"] not in _RAW_SQL_TOOLS]


async def get_resource_content() -> str:
    """Read all discovered MCP resources and return as formatted markdown.

    Results are cached after the first successful read since MCP resources
    are static reference content (OMOP conventions, vocabulary info, etc.)
    that doesn't change during the application lifecycle.

    Returns empty string if no resources are available.
    """
    global _resource_cache

    if _resource_cache is not None:
        return _resource_cache

    if not _resources:
        return ""

    sections: list[str] = []
    for res_info in _resources:
        server_name = res_info["server"]
        client = _clients.get(server_name)
        if not client:
            continue
        try:
            result = await client.read_resource(res_info["uri"])
            text = _extract_text(
                result.content if hasattr(result, "content") else result
            )
            sections.append(
                f"## {res_info['name']}\n\n{text}"
            )
        except Exception as e:
            logger.debug("Failed to read resource %s: %s", res_info["uri"], e)

    if not sections:
        return ""

    _resource_cache = "# MCP Resource Reference\n\n" + "\n\n---\n\n".join(sections)
    logger.info("MCP resource content cached (%d resources, %d chars)", len(sections), len(_resource_cache))
    return _resource_cache


async def execute_tool(name: str, arguments: dict) -> str:
    """Execute a tool by name via MCP protocol.

    Routes to the correct server based on tool name.
    On connection errors, attempts one reconnect + retry.
    Returns the result as a string suitable for the LLM.
    """
    server_name = _tool_to_server.get(name)
    if not server_name:
        return json.dumps({"error": f"Unknown tool: {name}"})

    client = _clients.get(server_name)
    if not client:
        return json.dumps({"error": f"Server {server_name} not connected"})

    try:
        result = await client.call_tool(name, arguments)
        return _extract_text(result.content if hasattr(result, "content") else result)
    except Exception as e:
        if not _is_connection_error(e):
            logger.error("MCP tool %s/%s failed: %s", server_name, name, e)
            return json.dumps({"error": str(e)})

        logger.warning(
            "MCP server %s connection lost during %s: %s. Reconnecting...",
            server_name, name, e,
        )
        if not await _reconnect_server(server_name):
            return json.dumps({
                "error": f"Server {server_name} disconnected and reconnect failed",
            })

        # Retry once on the fresh connection
        try:
            client = _clients[server_name]
            result = await client.call_tool(name, arguments)
            return _extract_text(
                result.content if hasattr(result, "content") else result
            )
        except Exception as retry_err:
            logger.error(
                "MCP tool %s/%s retry failed after reconnect: %s",
                server_name, name, retry_err,
            )
            return json.dumps({"error": str(retry_err)})


def _extract_text(content: Any) -> str:
    """Extract text from MCP tool result content."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if hasattr(item, "text"):
                parts.append(item.text)
            elif isinstance(item, dict) and "text" in item:
                parts.append(item["text"])
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)
