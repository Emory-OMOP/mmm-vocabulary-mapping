"""Resolve free-text clinical strings to Standard Concepts via a two-step path:

    source_text → non-standard concept (embedding match) → Maps-to → Standard concept

Uses a separate DuckDB file (concept_embeddings_nonstandard.duckdb) containing
embeddings of non-standard and classification concepts. For each non-standard
candidate found by cosine similarity, follows the CONCEPT_RELATIONSHIP 'Maps to'
edge to arrive at one or more Standard target concepts. Returns Standard
concepts with provenance indicating which non-standard led to each.

This is complementary to the standard-only embedding search: the standard DB
embeds canonical names (SNOMED "Myocardial infarction"), while this path
embeds source vocabulary names (ICD10CM "Acute myocardial infarction, unspecified").
Source text that lexically matches source vocab names gets routed to the
appropriate standard target via the community-curated Maps-to relationships,
leveraging OHDSI's decades of manual mapping work.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import duckdb

logger = logging.getLogger(__name__)


NONSTANDARD_EMBEDDINGS_DB = os.environ.get(
    "OHDSI_NONSTANDARD_EMBEDDINGS_DB",
    os.path.join(
        os.path.dirname(os.environ.get("OHDSI_DUCKDB_PATH", "")),
        "concept_embeddings_nonstandard.duckdb",
    ),
)
VOCAB_DB = os.environ.get("OHDSI_DUCKDB_PATH", "")
VOCAB_SCHEMA = os.environ.get("OHDSI_VOCAB_SCHEMA", "main_vocab")
EMBED_MODEL = os.environ.get("OHDSI_EMBED_MODEL", "cambridgeltl/SapBERT-from-PubMedBERT-fulltext")
# Pin the exact Hugging Face revision (the one the winning run used) so the
# weights don't float to the model repo's latest commit.
EMBED_REVISION = os.environ.get("OHDSI_EMBED_REVISION", "090663c3ae57bf35ffe4d0d468a2a88d03051a4d")
EMBED_DIM = int(os.environ.get("OHDSI_EMBED_DIM", "768"))


# Lazy-loaded model singleton (shared with embedding_search.py's model cache semantics)
_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("Loading embedding model for non-standard resolver: %s @ %s", EMBED_MODEL, EMBED_REVISION)
        _model = SentenceTransformer(EMBED_MODEL, revision=EMBED_REVISION)
        logger.info("Model loaded on %s", _model.device)
    return _model


def is_available() -> bool:
    """Check if the non-standard embeddings database exists."""
    return os.path.exists(NONSTANDARD_EMBEDDINGS_DB) and os.path.exists(VOCAB_DB)


def resolve_standard_via_nonstandard(
    text: str,
    top_k_nonstandard: int = 20,
    top_k_standard: int = 10,
    target_domain: str | None = None,
    target_vocabulary_id: str | None = None,
) -> list[dict[str, Any]]:
    """Map free text to Standard concepts via non-standard embedding match + Maps-to.

    Args:
        text: Source text to resolve (e.g., "X-RAY OF WRIST").
        top_k_nonstandard: How many non-standard candidates to consider from
            embedding search. Default 20.
        top_k_standard: Maximum number of Standard concepts to return. Default 10.
        target_domain: Optional domain filter on the Standard target
            (e.g., 'Procedure', 'Measurement').
        target_vocabulary_id: Optional vocabulary filter on the Standard target
            (e.g., 'SNOMED').

    Returns:
        List of dicts ordered by best (max) non-standard similarity. Each entry:
            standard_concept_id: int
            standard_concept_name: str
            standard_vocabulary_id: str
            standard_domain_id: str
            standard_concept_class_id: str
            max_similarity: float        # best cosine sim among source paths
            n_source_paths: int          # how many non-standards led here
            source_paths: list[dict]     # provenance, ordered by similarity
                concept_id: int (non-standard)
                concept_name: str
                vocabulary_id: str
                similarity: float
    """
    if not is_available():
        logger.debug(
            "Non-standard embeddings DB or vocab DB not found (embeddings=%s, vocab=%s)",
            NONSTANDARD_EMBEDDINGS_DB, VOCAB_DB,
        )
        return []

    model = _get_model()
    query_vec = model.encode([text], normalize_embeddings=True)[0].tolist()

    db = duckdb.connect(NONSTANDARD_EMBEDDINGS_DB, read_only=True)
    try:
        db.execute("INSTALL vss; LOAD vss;")
        db.execute("SET hnsw_enable_experimental_persistence = true;")
        # Attach the main vocab DB read-only so we can join Maps-to + target metadata
        db.execute(f"ATTACH '{VOCAB_DB}' AS vocab (READ_ONLY)")

        target_conditions = ["tgt.standard_concept = 'S'", "tgt.invalid_reason IS NULL"]
        params: list[Any] = [query_vec, top_k_nonstandard]
        if target_domain:
            target_conditions.append("tgt.domain_id = ?")
            params.append(target_domain)
        if target_vocabulary_id:
            target_conditions.append("tgt.vocabulary_id = ?")
            params.append(target_vocabulary_id)
        target_where = " AND ".join(target_conditions)

        sql = f"""
            WITH nonstd_ranked AS (
                SELECT
                    concept_id,
                    concept_name,
                    vocabulary_id,
                    array_cosine_similarity(embedding, ?::FLOAT[{EMBED_DIM}]) AS similarity
                FROM concept_embeddings
                ORDER BY similarity DESC
                LIMIT ?
            )
            SELECT
                tgt.concept_id            AS std_id,
                tgt.concept_name          AS std_name,
                tgt.vocabulary_id         AS std_vocab,
                tgt.domain_id             AS std_domain,
                tgt.concept_class_id      AS std_class,
                ns.concept_id             AS ns_id,
                ns.concept_name           AS ns_name,
                ns.vocabulary_id          AS ns_vocab,
                ns.similarity             AS similarity
            FROM nonstd_ranked ns
            JOIN vocab.{VOCAB_SCHEMA}.concept_relationship cr
                ON cr.concept_id_1 = ns.concept_id
                AND cr.relationship_id = 'Maps to'
                AND cr.invalid_reason IS NULL
            JOIN vocab.{VOCAB_SCHEMA}.concept tgt
                ON tgt.concept_id = cr.concept_id_2
            WHERE {target_where}
            ORDER BY ns.similarity DESC
        """
        rows = db.execute(sql, params).fetchall()
    finally:
        db.close()

    # Group by standard concept; keep provenance ordered by similarity desc.
    grouped: dict[int, dict[str, Any]] = {}
    for row in rows:
        std_id = row[0]
        path_entry = {
            "concept_id": row[5],
            "concept_name": row[6],
            "vocabulary_id": row[7],
            "similarity": float(row[8]),
        }
        if std_id not in grouped:
            grouped[std_id] = {
                "standard_concept_id": std_id,
                "standard_concept_name": row[1],
                "standard_vocabulary_id": row[2],
                "standard_domain_id": row[3],
                "standard_concept_class_id": row[4],
                "max_similarity": path_entry["similarity"],
                "n_source_paths": 0,
                "source_paths": [],
            }
        g = grouped[std_id]
        g["source_paths"].append(path_entry)
        g["n_source_paths"] += 1
        if path_entry["similarity"] > g["max_similarity"]:
            g["max_similarity"] = path_entry["similarity"]

    results = list(grouped.values())
    results.sort(key=lambda r: r["max_similarity"], reverse=True)
    return results[:top_k_standard]
