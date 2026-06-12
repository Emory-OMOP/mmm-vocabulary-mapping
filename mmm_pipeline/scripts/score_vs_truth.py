#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["duckdb>=1.4", "pandas>=2.0", "openpyxl>=3.1"]
# ///
"""Score a condition's predictions against the MMM train-set ground truth.

Usage:
    uv run score_vs_truth.py <predictions.csv> [--truth path/to/train_set.xlsx]

predictions.csv must have columns:
    source_code, target_concept_id, predicate

Outputs a summary report and a per-row error detail file alongside predictions.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import duckdb
import pandas as pd


# Repo root is two levels up: mmm_pipeline/scripts/ -> mmm_pipeline/ -> repo root.
# Override with OHDSI_DUCKDB_PATH / the --vocab-db and --truth flags.
_REPO = Path(__file__).resolve().parents[2]
VOCAB_DB = Path(
    os.environ.get("OHDSI_DUCKDB_PATH", str(_REPO / "omop_vocab.duckdb"))
)
TRAIN_DEFAULT = _REPO / "mmm_pipeline" / "source_sets" / "train_set.xlsx"


def load_truth(path: Path) -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name="in")
    return df[[
        "source_data_identifier", "source_code",
        "target_concept_id", "alternative_target_concept_id", "predicate",
    ]].copy()


def load_predictions(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = {"source_data_identifier", "source_code", "target_concept_id", "predicate"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Predictions missing columns: {missing}")
    return df


def parent_within_n_levels(con, pred_id: int, truth_id: int, n: int = 3) -> bool:
    """True if pred and truth are in the same ancestor-descendant chain within n levels."""
    if pd.isna(pred_id) or pd.isna(truth_id):
        return False
    r = con.execute(
        """
        SELECT 1 FROM main_vocab.concept_ancestor
        WHERE ((ancestor_concept_id = ? AND descendant_concept_id = ?)
            OR (ancestor_concept_id = ? AND descendant_concept_id = ?))
          AND min_levels_of_separation <= ?
        LIMIT 1
        """,
        [int(pred_id), int(truth_id), int(truth_id), int(pred_id), n],
    ).fetchone()
    return r is not None


def score(preds: pd.DataFrame, truth: pd.DataFrame, con) -> dict:
    # The train/test sets have deliberate 1:many rows (e.g., multi-drug chemo
    # regimens). Each (source_data_identifier, source_code) can repeat N times
    # in BOTH truth and preds. Merging on those keys produces a cartesian
    # (e.g., 5 preds × 5 truths = 25 rows for XC512) that inflates denominators.
    #
    # Correct semantics: position-wise comparison — the Nth pred row matches
    # against the Nth truth row. We align by (source_data_identifier,
    # source_code) + within-group row order.
    #
    # Force source_code and source_data_identifier to str on both sides —
    # pandas reads numeric-looking xlsx cells as int but CSV reads them as
    # object/str (or vice versa), so merge silently loses rows on dtype
    # mismatch. Normalizing to str guarantees keys align.
    preds = preds.copy()
    truth = truth.copy()
    for df in (preds, truth):
        df["source_code"] = df["source_code"].astype(str)
        df["source_data_identifier"] = df["source_data_identifier"].astype(str)
    preds["_pos"] = preds.groupby(["source_data_identifier", "source_code"]).cumcount()
    truth["_pos"] = truth.groupby(["source_data_identifier", "source_code"]).cumcount()

    merged = preds.merge(
        truth,
        on=["source_data_identifier", "source_code", "_pos"],
        how="left",
        suffixes=("_pred", "_truth"),
    )
    if merged["target_concept_id_truth"].isna().any():
        missing = merged[merged["target_concept_id_truth"].isna()][
            ["source_data_identifier", "source_code"]
        ].drop_duplicates()
        print(f"WARNING: {len(missing)} (sdi, source_code, pos) entries not in truth set")

    # Exact concept_id match (against primary or alternative)
    merged["concept_id_exact"] = (
        (merged["target_concept_id_pred"] == merged["target_concept_id_truth"])
        | (merged["target_concept_id_pred"] == merged["alternative_target_concept_id"])
    )

    # Predicate match
    merged["predicate_match"] = (
        merged["predicate_pred"].str.lower() == merged["predicate_truth"].str.lower()
    )

    # Parent-within-3-levels match (more forgiving)
    merged["parent_match_3"] = merged.apply(
        lambda r: parent_within_n_levels(con, r["target_concept_id_pred"], r["target_concept_id_truth"], 3),
        axis=1,
    )

    # Joint exact (concept_id + predicate both right)
    merged["joint_exact"] = merged["concept_id_exact"] & merged["predicate_match"]

    n = len(merged)
    report = {
        "n_rows": n,
        "concept_id_exact": merged["concept_id_exact"].sum(),
        "concept_id_exact_pct": round(100 * merged["concept_id_exact"].mean(), 2),
        "predicate_match": merged["predicate_match"].sum(),
        "predicate_match_pct": round(100 * merged["predicate_match"].mean(), 2),
        "parent_match_3": merged["parent_match_3"].sum(),
        "parent_match_3_pct": round(100 * merged["parent_match_3"].mean(), 2),
        "joint_exact": merged["joint_exact"].sum(),
        "joint_exact_pct": round(100 * merged["joint_exact"].mean(), 2),
    }
    return report, merged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("predictions", type=Path)
    parser.add_argument("--truth", type=Path, default=TRAIN_DEFAULT)
    parser.add_argument("--vocab-db", type=Path, default=VOCAB_DB)
    args = parser.parse_args()

    preds = load_predictions(args.predictions)
    truth = load_truth(args.truth)
    con = duckdb.connect(str(args.vocab_db), read_only=True)

    report, detail = score(preds, truth, con)
    con.close()

    print("Scoring report")
    print("=" * 50)
    for k, v in report.items():
        print(f"  {k:<24} {v}")

    detail_path = args.predictions.with_suffix(".detail.csv")
    detail.to_csv(detail_path, index=False)
    print(f"\nPer-row detail written to: {detail_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
