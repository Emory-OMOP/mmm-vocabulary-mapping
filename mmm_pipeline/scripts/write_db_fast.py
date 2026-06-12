#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = ["duckdb>=1.4", "numpy>=1.26", "pyarrow>=14"]
# ///
"""Fast replacement for embed_concepts.py phase 2.

The original script uses Python `executemany` with row-at-a-time inserts of
768-element float lists. At ~2200 rows/s this takes ~25 min for 3.25M concepts.

This script uses DuckDB's native PyArrow ingestion with a FixedSizeList array
column — column-oriented, vectorized, zero-copy from numpy. Typically 10x+
faster than executemany.

Usage:
    uv run write_db_fast.py \\
        --npy concept_embeddings.duckdb.embeddings.npy \\
        --vocab-db ~/.../omop_vocab.duckdb \\
        --filter standard \\
        --out concept_embeddings.duckdb \\
        --embed-dim 768

The script reads embeddings from the memory-mapped .npy (produced by
embed_concepts.py phase 1) and re-queries the vocab DB for metadata.
The .npy is in SELECT-order: `ORDER BY concept_id`, same filter as was used
for phase 1. This script repeats that query to get metadata in the same
order, then writes via DuckDB's native PyArrow ingestion.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import pyarrow as pa


def query_metadata(vocab_db: str, vocab_schema: str, filter_mode: str) -> tuple:
    """Re-query vocab DB for metadata in the same SELECT order as phase 1.

    filter_mode: 'standard' | 'nonstandard' | 'all'
    """
    if filter_mode == "standard":
        where = "standard_concept = 'S' AND invalid_reason IS NULL"
    elif filter_mode == "nonstandard":
        where = "COALESCE(standard_concept,'X')!='S' AND invalid_reason IS NULL"
    elif filter_mode == "all":
        where = "invalid_reason IS NULL"
    else:
        raise ValueError(f"Unknown filter_mode: {filter_mode}")

    con = duckdb.connect(vocab_db, read_only=True)
    rows = con.execute(f"""
        SELECT concept_id, concept_name, vocabulary_id, domain_id, concept_code, concept_class_id
        FROM {vocab_schema}.concept
        WHERE {where}
        ORDER BY concept_id
    """).fetchall()
    con.close()
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--npy", required=True, help="Raw embeddings .npy file")
    parser.add_argument("--vocab-db", required=True, help="Vocab DuckDB (source for metadata)")
    parser.add_argument("--vocab-schema", default="main_vocab")
    parser.add_argument("--filter", choices=["standard", "nonstandard", "all"], default="standard",
                        help="Which filter was used in phase 1 (must match to get correct ordering)")
    parser.add_argument("--out", required=True, help="Output DuckDB file")
    parser.add_argument("--embed-dim", type=int, default=768)
    parser.add_argument("--skip-index", action="store_true", help="Skip HNSW index build")
    args = parser.parse_args()

    out = Path(args.out)
    if out.exists():
        print(f"Removing existing {out}...")
        out.unlink()
        for suffix in (".wal",):
            p = out.with_suffix(out.suffix + suffix)
            if p.exists():
                p.unlink()

    print("=" * 60)
    print("PHASE 2 (FAST): PyArrow → DuckDB bulk insert")
    print("=" * 60)

    t0 = time.time()

    print(f"Re-querying metadata from {args.vocab_db} (filter={args.filter})...")
    t_meta = time.time()
    rows = query_metadata(args.vocab_db, args.vocab_schema, args.filter)
    total = len(rows)
    print(f"  Got metadata for {total:,} concepts in {time.time() - t_meta:.1f}s")

    # Unpack into columnar lists for efficient PyArrow construction
    concept_ids = np.array([r[0] for r in rows], dtype=np.int32)
    concept_names = np.array([r[1] for r in rows], dtype=object)
    vocabulary_ids = np.array([r[2] for r in rows], dtype=object)
    domain_ids = np.array([r[3] for r in rows], dtype=object)
    concept_codes = np.array([r[4] for r in rows], dtype=object)
    concept_class_ids = np.array([r[5] for r in rows], dtype=object)
    del rows

    print(f"Memory-mapping embeddings from {args.npy}...")
    embeddings = np.load(args.npy, mmap_mode="r")
    print(f"  Mapped: {embeddings.shape} ({embeddings.dtype})")
    assert embeddings.shape == (total, args.embed_dim), \
        f"Shape mismatch: expected ({total}, {args.embed_dim}), got {embeddings.shape}"

    print("Building PyArrow table (zero-copy from numpy where possible)...")
    t_arrow = time.time()

    # FixedSizeList is the native PyArrow type that maps to DuckDB FLOAT[N]
    # `from_arrays` takes the flat value buffer + list_size; this is effectively
    # zero-copy against a C-contiguous float32 numpy array.
    emb_flat = np.ascontiguousarray(embeddings, dtype=np.float32).ravel()
    emb_col = pa.FixedSizeListArray.from_arrays(
        pa.array(emb_flat, type=pa.float32()),
        list_size=args.embed_dim,
    )

    table = pa.table({
        "concept_id": pa.array(concept_ids, type=pa.int32()),
        "concept_name": pa.array(concept_names.astype(str), type=pa.string()),
        "vocabulary_id": pa.array(vocabulary_ids.astype(str), type=pa.string()),
        "domain_id": pa.array(domain_ids.astype(str), type=pa.string()),
        "concept_code": pa.array(concept_codes.astype(str), type=pa.string()),
        "concept_class_id": pa.array(concept_class_ids.astype(str), type=pa.string()),
        "embedding": emb_col,
    })
    print(f"  Table built in {time.time() - t_arrow:.1f}s "
          f"({table.num_rows:,} rows, {table.num_columns} columns)")

    print(f"Writing to {out}...")
    t_write = time.time()
    db = duckdb.connect(str(out))
    db.execute("INSTALL vss; LOAD vss;")

    # Register the Arrow table as a virtual view then CTAS.
    # This avoids any Python-side loop — DuckDB ingests in C directly.
    db.register("emb_arrow", table)
    db.execute(f"""
        CREATE TABLE concept_embeddings (
            concept_id INTEGER,
            concept_name VARCHAR,
            vocabulary_id VARCHAR,
            domain_id VARCHAR,
            concept_code VARCHAR,
            concept_class_id VARCHAR,
            embedding FLOAT[{args.embed_dim}]
        )
    """)
    db.execute("INSERT INTO concept_embeddings SELECT * FROM emb_arrow")
    db.unregister("emb_arrow")

    elapsed = time.time() - t_write
    rate = total / elapsed if elapsed > 0 else 0
    print(f"  Wrote {total:,} rows in {elapsed:.1f}s ({rate:,.0f} rows/s)")

    # CHECKPOINT: flatten WAL + compact column segments.
    # Without this, the fast path leaves ~6-7 GB of uncompacted staging pages.
    print("Running CHECKPOINT to compact storage...")
    t_ckpt = time.time()
    db.execute("CHECKPOINT")
    print(f"  Checkpoint done in {time.time() - t_ckpt:.1f}s")

    if not args.skip_index:
        print("=" * 60)
        print("PHASE 3: HNSW index")
        print("=" * 60)
        # Required to create HNSW index on a persistent DB (flagged experimental)
        db.execute("SET hnsw_enable_experimental_persistence = true")
        t_idx = time.time()
        db.execute("""
            CREATE INDEX concept_embeddings_hnsw
            ON concept_embeddings
            USING HNSW (embedding)
            WITH (metric = 'cosine', ef_construction = 128, M = 16)
        """)
        print(f"  Index built in {time.time() - t_idx:.1f}s")

    db.close()
    print()
    print(f"Total elapsed: {time.time() - t0:.1f}s")
    print(f"Output: {out} ({out.stat().st_size / (1024**3):.2f} GB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
