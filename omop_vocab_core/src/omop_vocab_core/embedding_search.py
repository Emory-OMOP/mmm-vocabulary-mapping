"""Semantic concept search via SapBERT embeddings stored in DuckDB VSS.

Provides a fallback search tier for when ILIKE and synonym matching fail.
Uses a separate DuckDB file (concept_embeddings.duckdb) with precomputed
HNSW index for cosine similarity search.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Iterator

import duckdb

logger = logging.getLogger(__name__)

EMBEDDINGS_DB_PATH = os.environ.get(
    "OHDSI_EMBEDDINGS_DB",
    os.path.join(
        os.path.dirname(os.environ.get("OHDSI_DUCKDB_PATH", "")),
        "concept_embeddings.duckdb",
    ),
)
EMBED_MODEL = os.environ.get("OHDSI_EMBED_MODEL", "cambridgeltl/SapBERT-from-PubMedBERT-fulltext")
# Pin the exact Hugging Face revision so weights don't float to the model
# repo's latest commit. This is the revision the winning run used.
EMBED_REVISION = os.environ.get("OHDSI_EMBED_REVISION", "090663c3ae57bf35ffe4d0d468a2a88d03051a4d")
EMBED_DIM = int(os.environ.get("OHDSI_EMBED_DIM", "768"))

# Lazy-loaded model singleton
_model = None


def _get_model():
    """Lazy-load the embedding model on first use."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading embedding model: %s @ %s", EMBED_MODEL, EMBED_REVISION)
        _model = SentenceTransformer(EMBED_MODEL, revision=EMBED_REVISION)
        logger.info("Model loaded on %s", _model.device)
    return _model


def is_available() -> bool:
    """Check if the embeddings database exists and is accessible."""
    return os.path.exists(EMBEDDINGS_DB_PATH)


def search_embeddings(
    text: str,
    domain: str | None = None,
    vocabulary_id: str | None = None,
    standard_only: bool = True,
    limit: int = 10,
) -> list[dict]:
    """Search for concepts by semantic similarity using SapBERT embeddings.

    Returns list of dicts with concept metadata + similarity score.
    Returns empty list if embeddings database is not available.
    """
    if not is_available():
        logger.debug("Embeddings DB not found at %s — skipping semantic search", EMBEDDINGS_DB_PATH)
        return []

    model = _get_model()
    embedding = model.encode([text], normalize_embeddings=True)[0].tolist()

    # Build domain/vocab filter
    conditions = []
    filter_params: list = []

    if domain:
        conditions.append("domain_id = ?")
        filter_params.append(domain)
    if vocabulary_id:
        conditions.append("vocabulary_id = ?")
        filter_params.append(vocabulary_id)
    # Note: standard_only filter not needed — embeddings DB only contains
    # standard concepts (standard_concept = 'S' at generation time)

    where = " AND ".join(conditions) if conditions else "1=1"

    # Use CTE to compute similarity once, avoiding double embedding parameter
    # Param order: embedding (once in CTE), filter params, limit
    params = [embedding] + filter_params + [limit]

    db = duckdb.connect(EMBEDDINGS_DB_PATH, read_only=True)
    try:
        db.execute("LOAD vss;")
        db.execute("SET hnsw_enable_experimental_persistence = true;")

        rows = db.execute(f"""
            WITH scored AS (
                SELECT concept_id, concept_name, domain_id, vocabulary_id,
                       concept_class_id, concept_code,
                       array_cosine_similarity(embedding, ?::FLOAT[{EMBED_DIM}]) AS similarity
                FROM concept_embeddings
            )
            SELECT concept_id, concept_name, domain_id, vocabulary_id,
                   concept_class_id, concept_code, similarity
            FROM scored
            WHERE {where}
            ORDER BY similarity DESC
            LIMIT ?
        """, params).fetchall()
    finally:
        db.close()

    columns = [
        "concept_id", "concept_name", "domain_id", "vocabulary_id",
        "concept_class_id", "concept_code", "similarity",
    ]
    return [dict(zip(columns, row)) for row in rows]
