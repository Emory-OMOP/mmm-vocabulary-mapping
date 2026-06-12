#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.0", "duckdb>=1.4", "anthropic>=0.40"]
# ///
"""Recovery pass for MMM predictions where the primary pipeline failed to
emit a final JSON (LLM got stuck enumerating candidates, never committed).

For each row with target_concept_id IS NULL AND session_id != '':
  1. Read the FULL assistant message from webapp/data/sessions.db
     (sessions store the untruncated text — Langfuse caps at 2000 chars).
  2. Call opus-4-7 as a "reviewer" with the source + prior reasoning,
     asking for a single JSON commit. No tool access — opus only reads
     and emits.
  3. Validate the emitted concept_id against the vocab DB (same validator
     as mmm_pipeline_api.py).
  4. Patch the input CSV in place (adds recovered_by column) and write
     a detail file of what was recovered and why.

Usage:
    uv run mmm_recovery.py --preds results/api_train_haiku.csv
    uv run mmm_recovery.py --preds results/api_test_sonnet.csv --model claude-opus-4-7
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import anthropic
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from mmm_pipeline_api import validate_against_vocab, extract_json  # noqa: E402


# Repo root is two levels up: mmm_pipeline/scripts/ -> mmm_pipeline/ -> repo root.
_REPO = Path(__file__).resolve().parents[2]
SESSIONS_DB_DEFAULT = _REPO / "webapp" / "data" / "sessions.db"
DEFAULT_MODEL = "claude-opus-4-7"


REVIEWER_SYSTEM_PROMPT = """\
You are a clinical reviewer for an OHDSI procedure-concept mapping task. A
prior agent explored candidate concepts but failed to commit to a final
JSON answer. Your job: read the prior agent's reasoning and commit to a
SINGLE best target Standard concept.

Rules:
- Pick the candidate the prior agent's reasoning most clearly converged
  toward. If multiple candidates were surfaced, prefer SNOMED Procedure
  concepts in the target-vocabulary preference order:
  SNOMED > LOINC > CPT4 > HCPCS > ICD10PCS > ICD9Proc > OPCS4 > OMOP Ext.
  For drug procedures: RxNorm / RxNorm Extension / CVX.
- If the prior reasoning mentioned a concept_id explicitly as the best
  fit, prefer that one verbatim. Do NOT invent concept_ids.
- If the source specifies laterality, match it. Non-essential parts
  (unspecified, without X, per session) are fine to ignore.
- Predicate: exactMatch if the target fully carries the substantive
  clinical meaning; broadMatch if target is more general than source.
- Be decisive. It's better to commit to a broadMatch than return null.

Output JSON only, no prose before or after:
{
  "target_concept_id": <int>,
  "target_concept_name": "<str>",
  "target_vocabulary_id": "<str>",
  "predicate": "exactMatch" | "broadMatch",
  "reasoning": "<one sentence why this pick>"
}

If the prior reasoning is genuinely insufficient to pick any concept, output:
{
  "target_concept_id": null,
  "target_concept_name": null,
  "target_vocabulary_id": null,
  "predicate": null,
  "reasoning": "insufficient prior reasoning"
}
"""


def fetch_assistant_text(sessions_db: Path, session_id: str) -> str | None:
    """Return the concatenated assistant text for a session, or None if
    the session doesn't exist."""
    if not sessions_db.exists():
        return None
    con = sqlite3.connect(str(sessions_db))
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT role, content FROM messages WHERE session_id = ? "
            "ORDER BY created_at",
            (session_id,),
        ).fetchall()
    finally:
        con.close()
    parts = [r["content"] for r in rows if r["role"] == "assistant" and r["content"]]
    return "\n".join(parts) if parts else None


def build_reviewer_user_message(row: dict, prior_text: str) -> str:
    orig = row.get("original_source_name")
    orig_line = (
        f"Original (native-language): {orig}\n"
        if orig and str(orig) != "nan" and orig != row.get("source_name")
        else ""
    )
    # Cap the prior text at ~30k chars to stay under context limits while
    # keeping most of the reasoning. Opus handles 200k; we stay conservative.
    prior_clipped = prior_text[:30000]
    return (
        f"Source:\n"
        f"  source_data_identifier: {row.get('source_data_identifier')}\n"
        f"  source_code: {row.get('source_code')}\n"
        f"  English name: {row.get('source_name')}\n"
        f"{orig_line}"
        f"\n"
        f"Prior agent's reasoning and tool exploration "
        f"(may be verbose, truncated at 30k chars):\n"
        f"---\n"
        f"{prior_clipped}\n"
        f"---\n"
        f"Commit to a final JSON answer now."
    )


def call_reviewer(
    client: anthropic.Anthropic, model: str, user_msg: str
) -> tuple[str, dict]:
    """One-shot reviewer call. Returns (raw_text, usage_dict)."""
    # opus-4-7 rejects `temperature` — omit for that model family.
    kwargs = {
        "model": model,
        "max_tokens": 1024,
        "system": [
            {
                "type": "text",
                "text": REVIEWER_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [{"role": "user", "content": user_msg}],
    }
    if "opus-4-7" not in model:
        kwargs["temperature"] = 0.0
    resp = client.messages.create(**kwargs)
    text = "\n".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    usage = {
        "input": getattr(resp.usage, "input_tokens", 0),
        "output": getattr(resp.usage, "output_tokens", 0),
        "cache_read": getattr(resp.usage, "cache_read_input_tokens", 0) or 0,
        "cache_create": getattr(resp.usage, "cache_creation_input_tokens", 0) or 0,
    }
    return text, usage


def recover_row(
    client: anthropic.Anthropic,
    model: str,
    row: dict,
    sessions_db: Path,
) -> dict:
    """Attempt to recover one row. Returns a dict with patch fields
    (target_concept_id, target_concept_name, target_vocabulary_id,
    predicate, reasoning, recovered_by, recovery_error)."""
    session_id = str(row.get("session_id") or "").strip()
    out: dict = {
        "target_concept_id": row.get("target_concept_id"),
        "target_concept_name": row.get("target_concept_name"),
        "target_vocabulary_id": row.get("target_vocabulary_id"),
        "predicate": row.get("predicate"),
        "reasoning": row.get("reasoning"),
        "recovered_by": None,
        "recovery_error": None,
    }
    if not session_id:
        out["recovery_error"] = "no_session_id"
        return out

    prior = fetch_assistant_text(sessions_db, session_id)
    if not prior:
        out["recovery_error"] = f"no_assistant_text_for_session_{session_id[:8]}"
        return out

    user_msg = build_reviewer_user_message(row, prior)
    try:
        text, usage = call_reviewer(client, model, user_msg)
    except Exception as e:
        out["recovery_error"] = f"reviewer_call_failed: {str(e)[:200]}"
        return out

    parsed = extract_json(text)
    if parsed is None or isinstance(parsed, list):
        out["recovery_error"] = "reviewer_no_json"
        return out

    llm_cid = parsed.get("target_concept_id")
    if llm_cid is None:
        out["recovery_error"] = "reviewer_declined"
        out["reasoning"] = parsed.get("reasoning")
        return out

    # Skip the strict name-match — reviewer paraphrases sometimes (e.g.,
    # "non-stress test" vs vocab's "non-stress testing"). We still validate
    # that the concept_id exists + is Standard + not invalidated. The
    # authoritative name from the vocab DB replaces the LLM's wording.
    validated = validate_against_vocab(llm_cid, None, None)
    if validated["validation_error"]:
        out["recovery_error"] = f"reviewer_validation: {validated['validation_error']}"
        return out

    out.update({
        "target_concept_id": validated["target_concept_id"],
        "target_concept_name": validated["target_concept_name"],
        "target_vocabulary_id": validated["target_vocabulary_id"],
        "predicate": parsed.get("predicate"),
        "reasoning": parsed.get("reasoning"),
        "recovered_by": model,
    })
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preds", type=Path, required=True,
                        help="Predictions CSV (will be patched in place)")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        help="Reviewer model (default claude-opus-4-7)")
    parser.add_argument("--sessions-db", type=Path, default=SESSIONS_DB_DEFAULT)
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be patched without writing")
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ERROR: set ANTHROPIC_API_KEY", file=sys.stderr)
        return 2

    df = pd.read_csv(args.preds)
    null_mask = df["target_concept_id"].isna() & df["session_id"].notna() & (df["session_id"] != "")
    n_null = null_mask.sum()
    print(f"Predictions: {len(df)} rows; {n_null} candidates for recovery")
    if n_null == 0:
        print("Nothing to recover.")
        return 0

    client = anthropic.Anthropic()
    patches: list[dict] = []
    t0 = time.time()
    for idx in df[null_mask].index:
        row = df.loc[idx].to_dict()
        print(f"  recovering row {idx} (session={str(row.get('session_id'))[:8]}, "
              f"source_code={row.get('source_code')}) ...", end="", flush=True)
        patch = recover_row(client, args.model, row, args.sessions_db)
        patches.append({"row_index": idx, **patch})
        if patch.get("recovered_by"):
            print(f" ✓ concept_id={patch['target_concept_id']}")
        else:
            print(f" ✗ {patch.get('recovery_error')}")

    elapsed = round(time.time() - t0, 1)
    n_recovered = sum(1 for p in patches if p.get("recovered_by"))
    print(f"\nRecovered {n_recovered}/{n_null} rows in {elapsed}s")

    if args.dry_run:
        print("[dry-run] not writing CSV")
        return 0

    # Apply patches in place
    if "recovered_by" not in df.columns:
        df["recovered_by"] = None
    if "recovery_error" not in df.columns:
        df["recovery_error"] = None
    for p in patches:
        idx = p.pop("row_index")
        for k, v in p.items():
            df.at[idx, k] = v
    df.to_csv(args.preds, index=False)
    print(f"Patched in place: {args.preds}")

    detail_path = args.preds.with_suffix(".recovery.csv")
    pd.DataFrame(patches).to_csv(detail_path, index=False)
    print(f"Recovery detail: {detail_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
