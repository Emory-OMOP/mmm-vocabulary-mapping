#!/usr/bin/env bash
# Start the MMM vocabulary-mapping stack locally with uv (no Docker):
#   ohdsi-vocab MCP (:8001) + omcp read-only SQL (:8003) + webapp (:8000).
# Ctrl+C stops all three. The Docker path (docker compose up) is the simpler
# option — this is for running directly from a checkout.
#
# Prerequisites (see README "Data"):
#   OHDSI_DUCKDB_PATH                 OMOP vocabulary DuckDB (main_vocab schema)
#   OHDSI_EMBEDDINGS_DB               SapBERT Standard embeddings DuckDB
#   OHDSI_NONSTANDARD_EMBEDDINGS_DB   SapBERT non-standard embeddings DuckDB
#   ANTHROPIC_API_KEY, BETA_PASSKEY
#
# Usage:  bash scripts/start.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"

: "${OHDSI_DUCKDB_PATH:?set OHDSI_DUCKDB_PATH to your OMOP vocabulary DuckDB}"
: "${ANTHROPIC_API_KEY:?set ANTHROPIC_API_KEY}"
: "${BETA_PASSKEY:?set BETA_PASSKEY (the webapp login passkey)}"
export OHDSI_DUCKDB_PATH ANTHROPIC_API_KEY BETA_PASSKEY
export OHDSI_VOCAB_SCHEMA="${OHDSI_VOCAB_SCHEMA:-main_vocab}"

PIDS=()
cleanup() { echo; echo "Stopping..."; for p in "${PIDS[@]:-}"; do kill "$p" 2>/dev/null || true; done; wait 2>/dev/null || true; }
trap cleanup EXIT INT TERM

wait_for_port() {
  local port=$1 name=$2 n=0
  while [ $n -lt 60 ]; do
    if lsof -ti:"$port" >/dev/null 2>&1; then echo "  $name ready (:$port)"; return 0; fi
    sleep 1; n=$((n+1))
  done
  echo "  WARNING: $name not ready (:$port)"
}

echo "Syncing workspace deps (ohdsi-vocab)..."
(cd "$REPO" && uv sync --quiet)

# ── ohdsi-vocab → :8001 ──────────────────────────────────────────────────────
( cd "$REPO/mcp_server" && MCP_TRANSPORT=streamable-http MCP_PORT=8001 uv run python server.py ) &
PIDS+=($!); echo "  ohdsi-vocab → http://localhost:8001/mcp (PID $!)"

# ── omcp → :8003 ─────────────────────────────────────────────────────────────
( cd "$REPO/omcp" && \
    DB_TYPE=duckdb DB_PATH="$OHDSI_DUCKDB_PATH" DB_READ_ONLY=true \
    CDM_SCHEMA="$OHDSI_VOCAB_SCHEMA" VOCAB_SCHEMA="$OHDSI_VOCAB_SCHEMA" ENABLE_LANGFUSE=false \
    MCP_TRANSPORT=streamable-http MCP_HOST=localhost MCP_PORT=8003 \
    FASTMCP_HOST=localhost FASTMCP_PORT=8003 \
    uv run omcp ) &
PIDS+=($!); echo "  omcp → http://localhost:8003/mcp (PID $!)"

wait_for_port 8001 ohdsi-vocab
wait_for_port 8003 omcp

# ── webapp → :8000 (inject the MMM system prompt) ────────────────────────────
SYSTEM_PROMPT="$(cd "$REPO" && python3 -c 'import sys; sys.path.insert(0, "mmm_pipeline/scripts"); import system_prompt; print(system_prompt.SYSTEM_PROMPT)')"
export SYSTEM_PROMPT
( cd "$REPO/webapp" && \
    MCP_OHDSI_VOCAB_URL=http://localhost:8001/mcp MCP_OMCP_URL=http://localhost:8003/mcp \
    DEFAULT_PROVIDER=claude DEFAULT_MODEL="${OHDSI_AGENT_MODEL:-claude-opus-4-7}" \
    LANGFUSE_ENABLED=false \
    uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000 ) &
PIDS+=($!); echo "  webapp → http://localhost:8000 (PID $!)"

wait_for_port 8000 webapp
echo
echo "Stack up.  Health:  curl -s localhost:8000/api/health"
echo "Run it:    cd mmm_pipeline/scripts && OHDSI_AGENT_FASTAPI_PASSKEY=\"\$BETA_PASSKEY\" uv run mmm_pipeline_api.py ../source_sets/test_set.xlsx --out ../results/api_test.csv"
echo "Ctrl+C to stop."
wait
