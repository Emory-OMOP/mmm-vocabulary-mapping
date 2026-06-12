#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["pandas>=2.0", "openpyxl>=3.1", "duckdb>=1.4"]
# ///
"""Format pipeline output for the MindMeetsMachines submission.

Input: a CSV produced by mmm_pipeline_api.py (or the A/B/C subagent
accumulators) with columns:
  source_data_identifier, source_code, target_concept_id, target_concept_name,
  target_vocabulary_id, predicate, reasoning, ...

Output: an xlsx file matching the challenge submission schema (same sheet
layout as test_set.xlsx but with target columns filled in). Also emits a
validation report.

Expected challenge submission columns (per the challenge rules):
  source_data_identifier, source_code, original_source_name, source_name,
  target_concept_id, target_concept_name, alternative_target_concept_id,
  alternative_target_concept_name, predicate

We leave `alternative_*` blank (the challenge says 1:many is permissible
but discouraged; we submit a single best target per row).

Usage:
    uv run submission_formatter.py \\
        --predictions ../results/condition_D/predictions_20260419.csv \\
        --test-set ../source_sets/test_set.xlsx \\
        --out ../results/submission.xlsx
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import duckdb
import pandas as pd


# Repo root is two levels up: mmm_pipeline/scripts/ -> mmm_pipeline/ -> repo root.
# Override with OHDSI_DUCKDB_PATH or the --vocab-db flag.
_REPO = Path(__file__).resolve().parents[2]
VOCAB_DB_DEFAULT = Path(
    os.environ.get("OHDSI_DUCKDB_PATH", str(_REPO / "omop_vocab.duckdb"))
)
VALID_PREDICATES = {"exactMatch", "broadMatch"}
SUBMISSION_COLUMNS = [
    "source_data_identifier",
    "source_code",
    "original_source_name",
    "source_name",
    "target_concept_id",
    "target_concept_name",
    "alternative_target_concept_id",
    "alternative_target_concept_name",
    "predicate",
]


def validate_targets_exist(target_ids: list[int], vocab_db: Path, schema: str = "main_vocab") -> dict[int, dict]:
    """Verify every predicted target_concept_id exists in the vocab DB and
    is a Standard concept. Returns a dict keyed by concept_id for the
    found ones. Missing / non-standard ids are flagged via the report."""
    ids = [int(i) for i in target_ids if pd.notna(i)]
    if not ids:
        return {}
    con = duckdb.connect(str(vocab_db), read_only=True)
    placeholder = ",".join(["?"] * len(ids))
    rows = con.execute(f"""
        SELECT concept_id, concept_name, vocabulary_id, domain_id,
               standard_concept, invalid_reason
        FROM {schema}.concept
        WHERE concept_id IN ({placeholder})
    """, ids).fetchall()
    con.close()
    return {
        r[0]: {
            "concept_name": r[1],
            "vocabulary_id": r[2],
            "domain_id": r[3],
            "standard_concept": r[4],
            "invalid_reason": r[5],
        }
        for r in rows
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, required=True,
                        help="CSV output from mmm_pipeline_api.py")
    parser.add_argument("--test-set", type=Path, required=True,
                        help="Original test_set.xlsx (for source columns)")
    parser.add_argument("--out", type=Path, required=True,
                        help="Output submission xlsx path")
    parser.add_argument("--vocab-db", type=Path, default=VOCAB_DB_DEFAULT)
    parser.add_argument("--vocab-schema", default="main_vocab")
    parser.add_argument("--strict", action="store_true",
                        help="Exit non-zero if any prediction fails validation")
    args = parser.parse_args()

    preds = pd.read_csv(args.predictions)
    test = pd.read_excel(args.test_set, sheet_name="in")

    print(f"Loaded {len(preds)} predictions and {len(test)} test rows")

    # CRITICAL: normalize merge-key dtypes. pandas reads numeric-looking
    # source_codes as int from xlsx but as str (or object) from CSV, and the
    # merge silently drops mismatched rows. Force both sides to str.
    for df in (preds, test):
        df["source_code"] = df["source_code"].astype(str)
        df["source_data_identifier"] = df["source_data_identifier"].astype(str)

    # Strip any prediction-target columns the input template may already have
    # (train_set.xlsx has ground-truth target_concept_id/name + predicate;
    # test_set.xlsx doesn't). Dropping them avoids column-collision suffixes
    # after the merge and makes the formatter robust to either input.
    drop_cols = [
        "target_concept_id", "target_concept_name",
        "alternative_target_concept_id", "alternative_target_concept_name",
        "predicate",
    ]
    test = test.drop(columns=[c for c in drop_cols if c in test.columns])

    # Join predictions onto test rows by source_code + source_data_identifier
    # (source_code can collide across institutions, so use both).
    pred_cols = [
        "source_data_identifier", "source_code",
        "target_concept_id", "target_concept_name", "predicate",
    ]
    # alternative_target_* is optional — include if the pipeline emitted it
    for opt in ("alternative_target_concept_id", "alternative_target_concept_name"):
        if opt in preds.columns:
            pred_cols.append(opt)
    merged = test.merge(
        preds[pred_cols],
        on=["source_data_identifier", "source_code"],
        how="left",
    )

    # --- Report ---
    n_total = len(merged)
    n_missing = merged["target_concept_id"].isna().sum()
    n_invalid_pred = (~merged["predicate"].fillna("").isin(VALID_PREDICATES | {""})).sum()

    # Validate target concepts against the vocab
    target_ids = merged["target_concept_id"].dropna().astype(int).tolist()
    catalog = validate_targets_exist(target_ids, args.vocab_db, args.vocab_schema)

    nonstd_targets = [
        cid for cid in target_ids
        if cid in catalog and catalog[cid]["standard_concept"] != "S"
    ]
    missing_in_vocab = [cid for cid in target_ids if cid not in catalog]

    print()
    print("=" * 60)
    print("Submission validation")
    print("=" * 60)
    print(f"  Total test rows:                 {n_total}")
    print(f"  Unmapped (target_concept_id null): {n_missing}")
    print(f"  Invalid predicate values:        {n_invalid_pred}")
    print(f"  Targets not Standard:            {len(nonstd_targets)}")
    print(f"  Targets not in vocab DB:         {len(missing_in_vocab)}")

    if nonstd_targets:
        print(f"  Non-standard target concept_ids: {nonstd_targets[:10]}")
    if missing_in_vocab:
        print(f"  Missing concept_ids:             {missing_in_vocab[:10]}")

    # --- Format as submission ---
    # Do NOT force alternative_target_* to None — pipeline may emit MULTIPLE
    # output rows per source for unavoidable multi-drug regimens (e.g., EVAIA).
    # Each such row carries one distinct target_concept_id. Alternative_target_*
    # columns are left null unless explicitly present in preds.
    for alt in ("alternative_target_concept_id", "alternative_target_concept_name"):
        if alt not in merged.columns:
            merged[alt] = None
    # Fill target_concept_name from the vocab authoritative source
    # (replaces whatever the LLM said, to ensure names match concept_ids).
    name_map = {cid: info["concept_name"] for cid, info in catalog.items()}
    merged["target_concept_name"] = merged["target_concept_id"].map(
        lambda cid: name_map.get(int(cid)) if pd.notna(cid) else None
    )

    out_df = merged[SUBMISSION_COLUMNS].copy()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(args.out, engine="openpyxl") as writer:
        out_df.to_excel(writer, sheet_name="in", index=False)
    print()
    print(f"Submission written to: {args.out}")

    if args.strict and (n_missing or n_invalid_pred or nonstd_targets or missing_in_vocab):
        print("ERROR: validation failed (--strict)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
