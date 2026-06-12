"""Concept set staging — session-level DuckDB for result lineage and curation."""

import json
import os
from contextlib import contextmanager
from pathlib import Path

import duckdb

DEFAULT_STAGING_PATH = str(
    Path.home() / ".ohdsi" / "staging" / "staging.duckdb"
)


def get_staging_db_path() -> str:
    """Get staging DB path from env var, defaulting to ~/.ohdsi/staging/staging.duckdb."""
    path = os.environ.get("CONCEPT_SET_STAGING_DB", DEFAULT_STAGING_PATH)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def get_staging_connection():
    """Context manager for read-write DuckDB connection to the staging DB."""
    db_path = get_staging_db_path()
    conn = duckdb.connect(db_path, read_only=False)
    try:
        yield conn
    finally:
        conn.close()


def init_staging_db() -> None:
    """Create staging tables and sequences if they don't exist (idempotent).

    Also cleans up ephemeral results from prior sessions (older than 1 hour).
    """
    with get_staging_connection() as conn:
        conn.execute("CREATE SEQUENCE IF NOT EXISTS result_id_seq START 1")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS results (
                result_id INTEGER PRIMARY KEY DEFAULT nextval('result_id_seq'),
                parent_result_id INTEGER REFERENCES results(result_id),
                tool_name TEXT NOT NULL,
                parameters TEXT,
                created_at TIMESTAMP DEFAULT current_timestamp,
                status TEXT DEFAULT 'ephemeral',
                draft_name TEXT,
                concept_count INTEGER DEFAULT 0,
                summary TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS result_concepts (
                result_id INTEGER REFERENCES results(result_id),
                row_index INTEGER,
                concept_id INTEGER NOT NULL,
                concept_name TEXT,
                domain_id TEXT,
                vocabulary_id TEXT,
                concept_class_id TEXT,
                concept_code TEXT,
                standard_concept TEXT,
                include_descendants BOOLEAN DEFAULT FALSE,
                include_mapped BOOLEAN DEFAULT FALSE,
                is_excluded BOOLEAN DEFAULT FALSE,
                is_descendant BOOLEAN DEFAULT FALSE,
                source_concept_id INTEGER,
                PRIMARY KEY (result_id, row_index)
            )
        """)

    # Clean up stale ephemeral results from prior sessions (>60 minutes old)
    cleanup_ephemeral(older_than_minutes=60)


def create_result(
    tool_name: str,
    parameters: dict | None = None,
    parent_result_id: int | None = None,
) -> int:
    """Insert a new result row and return its result_id."""
    with get_staging_connection() as conn:
        params_json = json.dumps(parameters) if parameters else None
        row = conn.execute(
            """
            INSERT INTO results (tool_name, parameters, parent_result_id)
            VALUES (?, ?, ?)
            RETURNING result_id
            """,
            [tool_name, params_json, parent_result_id],
        ).fetchone()
        return row[0]


def add_result_concepts(result_id: int, concepts: list[dict]) -> None:
    """Bulk insert concepts for a result with auto-assigned row_index (0-based)."""
    if not concepts:
        return

    with get_staging_connection() as conn:
        for idx, c in enumerate(concepts):
            conn.execute(
                """
                INSERT INTO result_concepts (
                    result_id, row_index, concept_id, concept_name,
                    domain_id, vocabulary_id, concept_class_id, concept_code,
                    standard_concept, include_descendants, include_mapped,
                    is_excluded, is_descendant, source_concept_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    result_id,
                    idx,
                    c["concept_id"],
                    c.get("concept_name"),
                    c.get("domain_id"),
                    c.get("vocabulary_id"),
                    c.get("concept_class_id"),
                    c.get("concept_code"),
                    c.get("standard_concept"),
                    c.get("include_descendants", False),
                    c.get("include_mapped", False),
                    c.get("is_excluded", False),
                    c.get("is_descendant", False),
                    c.get("source_concept_id"),
                ],
            )
        conn.execute(
            "UPDATE results SET concept_count = ? WHERE result_id = ?",
            [len(concepts), result_id],
        )


def get_result(result_id: int) -> dict:
    """Return result metadata row as a dict."""
    with get_staging_connection() as conn:
        row = conn.execute(
            "SELECT * FROM results WHERE result_id = ?", [result_id]
        ).fetchone()
        if row is None:
            raise ValueError(f"Result {result_id} not found")
        columns = [desc[0] for desc in conn.description]
        return dict(zip(columns, row))


def get_result_concepts(
    result_id: int, include_concept_ids: bool = False
) -> list[dict]:
    """Return concept rows for a result.

    When include_concept_ids is False, concept_id is stripped from each dict.
    """
    with get_staging_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM result_concepts WHERE result_id = ? ORDER BY row_index",
            [result_id],
        ).fetchall()
        columns = [desc[0] for desc in conn.description]
        results = [dict(zip(columns, row)) for row in rows]
        if not include_concept_ids:
            for r in results:
                r.pop("concept_id", None)
        return results


def cherry_pick(
    parent_result_id: int,
    indices: list[int],
    tool_name: str = "cherry_pick",
) -> int:
    """Create a new child result containing only rows at given indices from parent."""
    with get_staging_connection() as conn:
        # Fetch parent concepts at the requested indices
        placeholders = ", ".join("?" for _ in indices)
        rows = conn.execute(
            f"""
            SELECT * FROM result_concepts
            WHERE result_id = ? AND row_index IN ({placeholders})
            ORDER BY row_index
            """,
            [parent_result_id, *indices],
        ).fetchall()
        columns = [desc[0] for desc in conn.description]
        parent_concepts = [dict(zip(columns, row)) for row in rows]

    # Create child result
    child_id = create_result(
        tool_name=tool_name,
        parameters={"indices": indices},
        parent_result_id=parent_result_id,
    )

    # Re-index and insert
    reindexed = []
    for concept in parent_concepts:
        concept.pop("result_id", None)
        concept.pop("row_index", None)
        reindexed.append(concept)

    add_result_concepts(child_id, reindexed)
    return child_id


def promote_result(result_id: int, draft_name: str) -> None:
    """Set a result's status to 'kept' and assign a draft_name."""
    with get_staging_connection() as conn:
        conn.execute(
            "UPDATE results SET status = 'kept', draft_name = ? WHERE result_id = ?",
            [draft_name, result_id],
        )


def list_results(status: str | None = None) -> list[dict]:
    """Return result summaries, optionally filtered by status."""
    with get_staging_connection() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM results WHERE status = ? ORDER BY result_id",
                [status],
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM results ORDER BY result_id"
            ).fetchall()
        columns = [desc[0] for desc in conn.description]
        return [dict(zip(columns, row)) for row in rows]


def list_drafts() -> list[dict]:
    """Return results where status is 'kept' or 'finalized'."""
    with get_staging_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM results WHERE status IN ('kept', 'finalized') ORDER BY result_id"
        ).fetchall()
        columns = [desc[0] for desc in conn.description]
        return [dict(zip(columns, row)) for row in rows]


def get_draft_concept_ids(draft_name: str) -> list[dict]:
    """Return concept_ids + flags for a named draft. Server-only, never returned to LLM."""
    with get_staging_connection() as conn:
        rows = conn.execute(
            """
            SELECT rc.concept_id, rc.include_descendants, rc.is_excluded, rc.include_mapped
            FROM result_concepts rc
            JOIN results r ON rc.result_id = r.result_id
            WHERE r.draft_name = ?
            ORDER BY rc.row_index
            """,
            [draft_name],
        ).fetchall()
        columns = [desc[0] for desc in conn.description]
        return [dict(zip(columns, row)) for row in rows]


def get_result_lineage(result_id: int) -> list[dict]:
    """Walk parent_result_id chain from root to given result using a recursive CTE."""
    with get_staging_connection() as conn:
        rows = conn.execute(
            """
            WITH RECURSIVE lineage AS (
                SELECT * FROM results WHERE result_id = ?
                UNION ALL
                SELECT r.* FROM results r
                JOIN lineage l ON r.result_id = l.parent_result_id
            )
            SELECT * FROM lineage ORDER BY result_id
            """,
            [result_id],
        ).fetchall()
        columns = [desc[0] for desc in conn.description]
        return [dict(zip(columns, row)) for row in rows]


def cleanup_ephemeral(older_than_minutes: int = 60) -> None:
    """Delete ephemeral results older than the given threshold.

    Skips ephemeral results that are ancestors of kept/finalized results
    (FK constraint on parent_result_id).
    """
    with get_staging_connection() as conn:
        # Find ephemeral results that are safe to delete:
        # old enough AND not referenced as parent by any other result
        conn.execute(
            """
            DELETE FROM result_concepts
            WHERE result_id IN (
                SELECT r.result_id FROM results r
                WHERE r.status = 'ephemeral'
                AND r.created_at < current_timestamp - INTERVAL (?) MINUTE
                AND r.result_id NOT IN (
                    SELECT parent_result_id FROM results
                    WHERE parent_result_id IS NOT NULL
                )
            )
            """,
            [older_than_minutes],
        )
        conn.execute(
            """
            DELETE FROM results
            WHERE status = 'ephemeral'
            AND created_at < current_timestamp - INTERVAL (?) MINUTE
            AND result_id NOT IN (
                SELECT parent_result_id FROM results
                WHERE parent_result_id IS NOT NULL
            )
            """,
            [older_than_minutes],
        )
