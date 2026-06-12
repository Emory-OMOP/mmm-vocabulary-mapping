#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.27", "pandas>=2.0", "openpyxl>=3.1", "aiofiles", "duckdb>=1.4"]
# ///
"""Condition D: Async API pipeline for MMM procedure mapping.

One HTTP call per source row to the OHDSI Agent webapp at /api/chat.
The webapp handles the tool-use loop server-side against ohdsi-vocab MCP.
No Claude Code subagent spawns, no CLAUDE.md bloat, no batch inertia.

Usage:
    uv run mmm_pipeline_api.py source_sets/test_set.xlsx --out results/api_test.csv
    uv run mmm_pipeline_api.py source_sets/train_set.xlsx --out results/api_train.csv --concurrency 10

Environment:
    OHDSI_AGENT_FASTAPI_URL       webapp base URL (default: http://localhost:8000)
    OHDSI_AGENT_FASTAPI_PASSKEY   passkey for /api/auth/login
    OHDSI_AGENT_FASTAPI_MODEL     model ID (default: claude-sonnet-4-5)
    OHDSI_AGENT_FASTAPI_PROVIDER  provider (default: claude)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pandas as pd

import duckdb  # noqa: E402

# Vocab DB validation — LLM emits concept_id directly (read from its
# reveal_concept_ids tool call), pipeline verifies against the vocab DB
# (exists + Standard + name match). Vocab DB is read-only in the pipeline
# and not written by anything during the run, so no lock contention.
# Repo root is two levels up: mmm_pipeline/scripts/ -> mmm_pipeline/ -> repo root.
# Override the DB location with OHDSI_DUCKDB_PATH.
_REPO = Path(__file__).resolve().parents[2]
VOCAB_DB_PATH = os.environ.get(
    "OHDSI_DUCKDB_PATH",
    str(_REPO / "omop_vocab.duckdb"),
)
VOCAB_SCHEMA = os.environ.get("OHDSI_VOCAB_SCHEMA", "main_vocab")


OHDSI_AGENT_FASTAPI_URL = os.environ.get("OHDSI_AGENT_FASTAPI_URL", "http://localhost:8000")
OHDSI_AGENT_FASTAPI_PASSKEY = os.environ.get("OHDSI_AGENT_FASTAPI_PASSKEY", "")
OHDSI_AGENT_FASTAPI_MODEL = os.environ.get("OHDSI_AGENT_FASTAPI_MODEL", "claude-sonnet-4-5")
OHDSI_AGENT_FASTAPI_PROVIDER = os.environ.get("OHDSI_AGENT_FASTAPI_PROVIDER", "claude")

# Import the canonical system prompt + user-message builder.
# The retrieval stays raw; rules live in the system prompt for LLM interpretation.
sys.path.insert(0, str(Path(__file__).parent))
from system_prompt import build_user_message


async def login(client: httpx.AsyncClient) -> str:
    if not OHDSI_AGENT_FASTAPI_PASSKEY:
        raise RuntimeError("OHDSI_AGENT_FASTAPI_PASSKEY environment variable must be set")
    r = await client.post(
        f"{OHDSI_AGENT_FASTAPI_URL}/api/auth/login",
        json={"passkey": OHDSI_AGENT_FASTAPI_PASSKEY},
        timeout=30.0,
    )
    r.raise_for_status()
    return r.json()["token"]


@dataclass
class AgentRun:
    """Parsed result of one /api/chat call."""
    text: str = ""
    tools_called: list[str] = field(default_factory=list)
    session_id: str = ""
    latency_sec: float = 0.0
    rounds: int = 0
    errors: list[str] = field(default_factory=list)


async def call_agent(client: httpx.AsyncClient, token: str, message: str) -> AgentRun:
    """Send one row to /api/chat, parse SSE events, return structured run data.

    Parses the webapp's SSE events (text, tool_call, tool_result, session,
    done, error). The MMM system prompt is injected server-side via the
    webapp's SYSTEM_PROMPT env var; here we only send the row-specific user
    message.
    """
    run = AgentRun()
    t0 = time.monotonic()
    # opus-4-7 deprecated the `temperature` param; omit it for that model.
    # For sonnet/haiku we still pin temperature=0.0 for determinism.
    payload = {
        "message": message,
        "provider": OHDSI_AGENT_FASTAPI_PROVIDER,
        "model": OHDSI_AGENT_FASTAPI_MODEL,
    }
    if "opus-4-7" not in OHDSI_AGENT_FASTAPI_MODEL:
        payload["temperature"] = 0.0
    try:
        async with client.stream(
            "POST",
            f"{OHDSI_AGENT_FASTAPI_URL}/api/chat",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=180.0,
        ) as response:
            response.raise_for_status()
            text_parts: list[str] = []
            current_event: str | None = None
            async for line in response.aiter_lines():
                if line.startswith("event: "):
                    current_event = line[7:].strip()
                    continue
                if not line.startswith("data: "):
                    continue
                try:
                    data = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                if current_event == "text":
                    if t := data.get("text"):
                        text_parts.append(t)
                elif current_event == "tool_call":
                    run.tools_called.append(data.get("name", ""))
                elif current_event == "session":
                    run.session_id = data.get("session_id", "")
                elif current_event == "done":
                    run.rounds = data.get("rounds", 0)
                elif current_event == "error":
                    run.errors.append(data.get("error", "unknown"))
            run.text = "".join(text_parts)
    except httpx.TimeoutException:
        run.errors.append("timeout")
    except httpx.HTTPStatusError as e:
        run.errors.append(f"http_{e.response.status_code}")
    except Exception as e:
        run.errors.append(str(e)[:200])
    finally:
        run.latency_sec = round(time.monotonic() - t0, 2)
    return run


# Extract the last complete JSON value containing "target_concept_id".
# We scan for balanced braces/brackets rather than regex, because the
# "reasoning" field can contain braces or nested quotes. Returns either
# a dict (single target) or a list of dicts (multi-target array).
def extract_json(response: str) -> dict | list | None:
    """Pull the final JSON answer (object or array) from the response."""
    candidates: list[str] = []
    n = len(response)
    i = 0
    while i < n:
        ch0 = response[i]
        if ch0 not in ("{", "["):
            i += 1
            continue
        open_ch, close_ch = (ch0, "}" if ch0 == "{" else "]")
        depth = 0
        start = i
        in_str = False
        esc = False
        j = i
        while j < n:
            ch = response[j]
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = not in_str
            elif not in_str:
                if ch == open_ch:
                    depth += 1
                elif ch == close_ch:
                    depth -= 1
                    if depth == 0:
                        text = response[start:j + 1]
                        if '"target_concept_id"' in text:
                            candidates.append(text)
                        break
            j += 1
        i = j + 1

    for candidate in reversed(candidates):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def normalize_picks(parsed, n_targets: int) -> list[dict]:
    """Coerce the LLM output into a list of `n_targets` pick dicts.

    Handles: single dict (wraps in list), list (truncates/pads), null values.
    Pad with null picks when the LLM returned fewer than expected.
    """
    null_pick = {
        "target_concept_id": None, "target_concept_name": None,
        "target_vocabulary_id": None, "predicate": None, "reasoning": None,
    }
    if parsed is None:
        return [dict(null_pick) for _ in range(n_targets)]
    if isinstance(parsed, dict):
        picks = [parsed]
    elif isinstance(parsed, list):
        picks = [p if isinstance(p, dict) else dict(null_pick) for p in parsed]
    else:
        return [dict(null_pick) for _ in range(n_targets)]
    # Pad or truncate to exactly n_targets
    while len(picks) < n_targets:
        picks.append(dict(null_pick))
    return picks[:n_targets]


def _normalize_name(s: str | None) -> str:
    return (s or "").strip().lower()


def validate_against_vocab(
    concept_id: int | None,
    llm_concept_name: str | None,
    llm_vocabulary_id: str | None,
) -> dict:
    """Validate that the LLM-emitted concept_id exists, is Standard, and
    matches the name the LLM claimed.

    Returns {target_concept_id, target_concept_name, target_vocabulary_id,
    validation_error}. If validation fails, target_concept_id is set to None
    so downstream submission formatting drops the row.
    """
    if concept_id is None:
        return {
            "target_concept_id": None,
            "target_concept_name": None,
            "target_vocabulary_id": None,
            "validation_error": "no_concept_id",
        }
    try:
        cid = int(concept_id)
    except (TypeError, ValueError):
        return {
            "target_concept_id": None,
            "target_concept_name": None,
            "target_vocabulary_id": None,
            "validation_error": f"non_int_concept_id: {concept_id!r}",
        }
    try:
        conn = duckdb.connect(VOCAB_DB_PATH, read_only=True)
    except Exception as e:
        return {
            "target_concept_id": None,
            "target_concept_name": None,
            "target_vocabulary_id": None,
            "validation_error": f"vocab_open_failed: {e}",
        }
    try:
        row = conn.execute(
            f"""
            SELECT concept_id, concept_name, vocabulary_id, domain_id,
                   standard_concept, invalid_reason
            FROM {VOCAB_SCHEMA}.concept
            WHERE concept_id = ?
            """,
            [cid],
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return {
            "target_concept_id": None,
            "target_concept_name": None,
            "target_vocabulary_id": None,
            "validation_error": f"concept_id_{cid}_not_in_vocab",
        }
    concept_id_db, concept_name_db, vocab_db, domain_db, std, invalid = row
    if std != "S":
        return {
            "target_concept_id": None,
            "target_concept_name": concept_name_db,
            "target_vocabulary_id": vocab_db,
            "validation_error": f"concept_id_{cid}_not_standard (std={std!r})",
        }
    if invalid is not None:
        return {
            "target_concept_id": None,
            "target_concept_name": concept_name_db,
            "target_vocabulary_id": vocab_db,
            "validation_error": f"concept_id_{cid}_invalid ({invalid!r})",
        }
    # Name check — LLM's claimed name must match the vocab's authoritative name.
    # We use normalized (case-insensitive, stripped) match.
    if llm_concept_name and _normalize_name(llm_concept_name) != _normalize_name(concept_name_db):
        return {
            "target_concept_id": None,
            "target_concept_name": concept_name_db,
            "target_vocabulary_id": vocab_db,
            "validation_error": (
                f"name_mismatch: llm_said={llm_concept_name!r} "
                f"vocab_says={concept_name_db!r}"
            ),
        }
    return {
        "target_concept_id": concept_id_db,
        "target_concept_name": concept_name_db,
        "target_vocabulary_id": vocab_db,
        "validation_error": None,
    }


def _preview(text: str, n: int = 500) -> str:
    """Truncate + newline-escape for compact CSV storage."""
    if not text:
        return ""
    return text[:n].replace("\n", " \\n ")


def _row_skeleton(row: dict, pick_index: int = 0) -> dict:
    return {
        "source_data_identifier": row["source_data_identifier"],
        "source_code": row["source_code"],
        "source_name": row["source_name"],
        "target_concept_id": None,
        "target_concept_name": None,
        "target_vocabulary_id": None,
        "predicate": None,
        "reasoning": None,
        "pick_index": pick_index,
        "n_targets": 1,
        "llm_concept_id_raw": None,
        "llm_concept_name_raw": None,
        "validation_error": None,
        "session_id": "",
        "tools_called": "",
        "latency_sec": 0.0,
        "rounds": 0,
        "text_response_preview": "",
        "error": None,
    }


async def process_source(
    client: httpx.AsyncClient,
    token: str,
    row: dict,
    sem: asyncio.Semaphore,
) -> list[dict]:
    """Process one source row. Returns 1 output row normally, or N output
    rows if the LLM decided this source is an unavoidable multi-target
    (e.g., a multi-drug chemo regimen)."""
    async with sem:
        try:
            run = await call_agent(client, token, build_user_message(row))
            shared = {
                "session_id": run.session_id,
                "tools_called": "|".join(run.tools_called),
                "latency_sec": run.latency_sec,
                "rounds": run.rounds,
                "text_response_preview": _preview(run.text),
            }
            if run.errors:
                skel = _row_skeleton(row)
                skel.update(shared)
                skel["error"] = "|".join(run.errors)
                return [skel]
            parsed = extract_json(run.text)
            if parsed is None:
                skel = _row_skeleton(row)
                skel.update(shared)
                skel["error"] = "no_json_extracted"
                return [skel]
            # Normalize to a list of picks (single object wraps to 1-element list)
            if isinstance(parsed, dict):
                picks = [parsed]
            elif isinstance(parsed, list):
                picks = [p for p in parsed if isinstance(p, dict)] or [{}]
            else:
                picks = [{}]
            n = len(picks)
            outputs = []
            for idx, pick in enumerate(picks):
                skel = _row_skeleton(row, pick_index=idx)
                skel.update(shared)
                skel["n_targets"] = n
                llm_cid = pick.get("target_concept_id")
                llm_name = pick.get("target_concept_name")
                llm_vocab = pick.get("target_vocabulary_id")
                skel["llm_concept_id_raw"] = llm_cid
                skel["llm_concept_name_raw"] = llm_name
                validated = validate_against_vocab(llm_cid, llm_name, llm_vocab)
                skel.update({
                    "target_concept_id": validated["target_concept_id"],
                    "target_concept_name": validated["target_concept_name"],
                    "target_vocabulary_id": validated["target_vocabulary_id"],
                    "predicate": pick.get("predicate"),
                    "reasoning": pick.get("reasoning"),
                    "validation_error": validated["validation_error"],
                })
                if validated["validation_error"]:
                    skel["error"] = validated["validation_error"]
                outputs.append(skel)
            return outputs
        except Exception as e:
            skel = _row_skeleton(row)
            skel["error"] = str(e)
            return [skel]


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_xlsx", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--limit", type=int, default=None, help="Process only first N rows")
    args = parser.parse_args()

    df = pd.read_excel(args.input_xlsx, sheet_name="in")
    if args.limit:
        df = df.head(args.limit)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(args.concurrency)

    # Group by unique (sdi, source_code) so we don't send the same source
    # to the LLM twice. The LLM decides if the source is single-target or
    # unavoidable multi-target (e.g., a multi-drug regimen) — for multi,
    # the LLM returns an array and we emit one output row per array element.
    unique_df = df.drop_duplicates(
        subset=["source_data_identifier", "source_code"], keep="first"
    )

    async with httpx.AsyncClient() as client:
        token = await login(client)
        print(
            f"Logged in. Processing {len(unique_df)} unique sources "
            f"({len(df)} input rows) with concurrency={args.concurrency}..."
        )

        tasks = [
            process_source(client, token, r.to_dict(), sem)
            for _, r in unique_df.iterrows()
        ]
        all_rows: list[dict] = []
        for i, coro in enumerate(asyncio.as_completed(tasks), 1):
            rows = await coro
            all_rows.extend(rows)
            if i % 10 == 0 or i == len(tasks):
                errs = sum(1 for r in all_rows if r["error"])
                print(f"  {i}/{len(tasks)} sources done ({len(all_rows)} total rows, {errs} errors)")

    out_df = pd.DataFrame(all_rows)
    out_df.to_csv(args.out, index=False)
    print(f"\nResults written to: {args.out}")

    errs = out_df[out_df["error"].notna()]
    if len(errs):
        print(f"Errors: {len(errs)} rows. First few:")
        print(errs[["source_code", "error"]].head().to_string())
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
