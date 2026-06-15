#!/usr/bin/env bash
# Inject the MMM system prompt (task + verbatim mapping rules + tool guidance +
# output schema) into the webapp via SYSTEM_PROMPT, unless the caller already
# set one, then start the FastAPI backend. `python`/`uvicorn` resolve from the
# venv on PATH (/app/.venv/bin) — no uv at runtime.
set -euo pipefail

if [ -z "${SYSTEM_PROMPT:-}" ]; then
  export SYSTEM_PROMPT="$(python -c 'import sys; sys.path.insert(0, "/app/mmm_prompt"); import system_prompt; print(system_prompt.SYSTEM_PROMPT)')"
fi

exec uvicorn backend.main:app --host 0.0.0.0 --port 8000
