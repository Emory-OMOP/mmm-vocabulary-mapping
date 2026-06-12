#!/bin/bash
# Generate SapBERT name-only embeddings for NON-STANDARD OMOP concepts.
#
# This builds concept_embeddings_nonstandard.duckdb — the embedding index that
# powers the `standard_via_nonstandard` retrieval tool (source-vocabulary text
# -> non-standard concept -> "Maps to" -> Standard concept).
#
# Two-step pipeline:
#   1. A phase-1 batch embedder writes a memory-mapped .npy of SapBERT vectors
#      for every NON-standard concept name (COALESCE(standard_concept,'X')!='S',
#      i.e. NULL and 'C' classifications).
#   2. write_db_fast.py (shipped in this directory) does phase 2+3 via PyArrow
#      + CHECKPOINT + HNSW to produce the queryable DuckDB index.
#
# NOTE ON PHASE 1: the original Emory run drove phase 1 with an external batch
# embedder (`embed_concepts.py` from a separate internal tool) which is NOT
# bundled in this public repo. Any SapBERT batch-embedder works — it must read
# concept names from `${VOCAB_SCHEMA}.concept` filtered to non-standard rows,
# in `ORDER BY concept_id`, and write a float32 [.npy] of shape (N, 768) at
# $NPY_PATH. Point EMBED_PHASE1 at your embedder, or obtain the prebuilt
# database from the data release (see the project README). The simplest path is
# to download the prebuilt embeddings DB rather than regenerate it.
#
# All paths below are configurable via environment variables.

set -euo pipefail

# Phase-1 batch embedder (external — see NOTE above). Must accept the env vars
# exported in Step 2 (DUCKDB_PATH, EMBED_MODEL, EMBED_DIM, TEXT_MODE, EMBED_DB).
EMBED_PHASE1="${EMBED_PHASE1:?Set EMBED_PHASE1 to your SapBERT phase-1 batch embedder (see header note)}"
VOCAB_DB="${OHDSI_DUCKDB_PATH:?Set OHDSI_DUCKDB_PATH to your OMOP vocabulary DuckDB}"
MODEL_ID="${OHDSI_EMBED_MODEL:-cambridgeltl/SapBERT-from-PubMedBERT-fulltext}"
OUT_DIR="${OUT_DIR:-$(dirname "$VOCAB_DB")}"
FAST_WRITER="${FAST_WRITER:-$(dirname "$0")/write_db_fast.py}"

TMP=$(mktemp -d -t mmm_nonstd_XXXXXX)
trap "rm -rf $TMP" EXIT

NPY_PATH="$OUT_DIR/concept_embeddings_nonstandard.duckdb.embeddings.npy"
OUT_DB="$OUT_DIR/concept_embeddings_nonstandard.duckdb"

echo "=== Step 1/2: Phase 1 — embed non-standard concept names (SapBERT) ==="

# Clean any stale nonstandard artifacts.
rm -f "$NPY_PATH" "$OUT_DB" "$OUT_DB.wal"

# Config passed to the phase-1 embedder. It must embed every non-standard
# concept name — filter COALESCE(standard_concept,'X')!='S' (NULL and 'C'),
# ORDER BY concept_id — with $EMBED_MODEL (name-only text, 768-dim) and write a
# float32 .npy of shape (N, 768) to $NPY_PATH (== $EMBED_DB + ".embeddings.npy").
export DUCKDB_PATH="$VOCAB_DB"
export EMBED_MODEL="$MODEL_ID"
export EMBED_DIM=768
export TEXT_MODE="name_only"
export EMBED_DB="$OUT_DB"
export EMBED_FILTER="COALESCE(standard_concept,'X')!='S'"
export CHECKPOINT_FILE="$OUT_DIR/concept_embeddings_nonstandard.npz"

echo "Embedder: $EMBED_PHASE1"
echo "Model:    $MODEL_ID"
echo "Filter:   non-standards (standard_concept IS NULL or 'C')"
echo "Vocab:    $VOCAB_DB"
echo "NPY out:  $NPY_PATH"
echo "DB out:   $OUT_DB"
echo ""

"$EMBED_PHASE1"

if [ ! -s "$NPY_PATH" ]; then
  echo "ERROR: Phase 1 did not produce $NPY_PATH"
  exit 1
fi

echo ""
echo "=== Step 2/2: Fast phase 2+3 via write_db_fast.py ==="
uv run python "$FAST_WRITER" \
  --npy "$NPY_PATH" \
  --vocab-db "$VOCAB_DB" \
  --filter nonstandard \
  --out "$OUT_DB" \
  --embed-dim 768

echo ""
echo "=== Done ==="
ls -lh "$OUT_DB" "$NPY_PATH"
