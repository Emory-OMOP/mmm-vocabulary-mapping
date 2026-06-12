"""Tests for concept set staging infrastructure."""

import os

import pytest

from omop_vocab_core.staging import (
    add_result_concepts,
    cherry_pick,
    cleanup_ephemeral,
    create_result,
    get_draft_concept_ids,
    get_result,
    get_result_concepts,
    get_result_lineage,
    init_staging_db,
    list_drafts,
    list_results,
    promote_result,
)


@pytest.fixture(autouse=True)
def staging_db(tmp_path, monkeypatch):
    """Point staging DB at a temporary file for test isolation."""
    db_path = str(tmp_path / "test_staging.duckdb")
    monkeypatch.setenv("CONCEPT_SET_STAGING_DB", db_path)
    init_staging_db()
    return db_path


SAMPLE_CONCEPTS = [
    {
        "concept_id": 201826,
        "concept_name": "Type 2 diabetes mellitus",
        "domain_id": "Condition",
        "vocabulary_id": "SNOMED",
        "concept_class_id": "Clinical Finding",
        "concept_code": "44054006",
        "standard_concept": "S",
    },
    {
        "concept_id": 4193704,
        "concept_name": "Type 2 diabetes mellitus without complication",
        "domain_id": "Condition",
        "vocabulary_id": "SNOMED",
        "concept_class_id": "Clinical Finding",
        "concept_code": "313436004",
        "standard_concept": "S",
        "include_descendants": True,
    },
    {
        "concept_id": 443238,
        "concept_name": "Diabetic neuropathy",
        "domain_id": "Condition",
        "vocabulary_id": "SNOMED",
        "concept_class_id": "Clinical Finding",
        "concept_code": "230572002",
        "standard_concept": "S",
        "is_excluded": True,
    },
]


def test_init_idempotent():
    """Calling init_staging_db twice should not error."""
    init_staging_db()
    init_staging_db()


def test_create_and_get_result():
    """Round-trip: create a result with concepts, then retrieve them."""
    rid = create_result("search_concepts", parameters={"query": "diabetes"})
    add_result_concepts(rid, SAMPLE_CONCEPTS)

    result = get_result(rid)
    assert result["tool_name"] == "search_concepts"
    assert result["concept_count"] == 3
    assert result["status"] == "ephemeral"
    assert result["parent_result_id"] is None


def test_get_result_concepts_with_and_without_ids():
    """Test that include_concept_ids controls concept_id visibility."""
    rid = create_result("search_concepts")
    add_result_concepts(rid, SAMPLE_CONCEPTS)

    # With concept_ids
    with_ids = get_result_concepts(rid, include_concept_ids=True)
    assert len(with_ids) == 3
    assert "concept_id" in with_ids[0]
    assert with_ids[0]["concept_id"] == 201826

    # Without concept_ids (default)
    without_ids = get_result_concepts(rid, include_concept_ids=False)
    assert len(without_ids) == 3
    assert "concept_id" not in without_ids[0]
    assert "concept_name" in without_ids[0]


def test_cherry_pick():
    """Cherry-pick creates a child with correct parent and subset."""
    parent_id = create_result("search_concepts")
    add_result_concepts(parent_id, SAMPLE_CONCEPTS)

    child_id = cherry_pick(parent_id, [0, 2])

    child = get_result(child_id)
    assert child["parent_result_id"] == parent_id
    assert child["concept_count"] == 2
    assert child["tool_name"] == "cherry_pick"

    child_concepts = get_result_concepts(child_id, include_concept_ids=True)
    assert len(child_concepts) == 2
    # Re-indexed: original indices 0,2 become 0,1
    assert child_concepts[0]["concept_id"] == 201826
    assert child_concepts[1]["concept_id"] == 443238
    assert child_concepts[0]["row_index"] == 0
    assert child_concepts[1]["row_index"] == 1


def test_promote_result():
    """Promote sets status and draft_name."""
    rid = create_result("search_concepts")
    add_result_concepts(rid, SAMPLE_CONCEPTS)

    promote_result(rid, "t2dm_concepts")

    result = get_result(rid)
    assert result["status"] == "kept"
    assert result["draft_name"] == "t2dm_concepts"


def test_list_results_filters_by_status():
    """list_results with status filter returns only matching results."""
    r1 = create_result("tool_a")
    r2 = create_result("tool_b")
    promote_result(r2, "draft_b")

    all_results = list_results()
    assert len(all_results) == 2

    ephemeral = list_results(status="ephemeral")
    assert len(ephemeral) == 1
    assert ephemeral[0]["result_id"] == r1

    kept = list_results(status="kept")
    assert len(kept) == 1
    assert kept[0]["result_id"] == r2


def test_list_drafts():
    """list_drafts returns only kept/finalized results."""
    r1 = create_result("tool_a")
    r2 = create_result("tool_b")
    r3 = create_result("tool_c")
    promote_result(r2, "draft_b")
    promote_result(r3, "draft_c")

    drafts = list_drafts()
    assert len(drafts) == 2
    draft_names = {d["draft_name"] for d in drafts}
    assert draft_names == {"draft_b", "draft_c"}


def test_get_draft_concept_ids():
    """get_draft_concept_ids returns concept_ids and flags for named draft."""
    rid = create_result("search_concepts")
    add_result_concepts(rid, SAMPLE_CONCEPTS)
    promote_result(rid, "t2dm_concepts")

    draft_ids = get_draft_concept_ids("t2dm_concepts")
    assert len(draft_ids) == 3
    assert draft_ids[0]["concept_id"] == 201826
    assert draft_ids[0]["include_descendants"] is False
    assert draft_ids[1]["include_descendants"] is True
    assert draft_ids[2]["is_excluded"] is True


def test_get_result_lineage():
    """Lineage returns correct chain from root to leaf."""
    r1 = create_result("search_concepts")
    add_result_concepts(r1, SAMPLE_CONCEPTS)

    r2 = cherry_pick(r1, [0, 1])
    r3 = cherry_pick(r2, [0])

    lineage = get_result_lineage(r3)
    assert len(lineage) == 3
    assert lineage[0]["result_id"] == r1
    assert lineage[1]["result_id"] == r2
    assert lineage[2]["result_id"] == r3


def test_cleanup_ephemeral():
    """cleanup_ephemeral removes old ephemeral but not kept results."""
    from omop_vocab_core.staging import get_staging_connection

    r1 = create_result("old_tool")
    add_result_concepts(r1, SAMPLE_CONCEPTS[:1])

    r2 = create_result("kept_tool")
    add_result_concepts(r2, SAMPLE_CONCEPTS[:1])
    promote_result(r2, "keeper")

    # Backdate r1 to 48 hours ago
    with get_staging_connection() as conn:
        conn.execute(
            "UPDATE results SET created_at = current_timestamp - INTERVAL 48 HOUR WHERE result_id = ?",
            [r1],
        )

    cleanup_ephemeral(older_than_hours=24)

    # r1 should be gone
    with pytest.raises(ValueError, match="not found"):
        get_result(r1)

    # r2 should still exist
    result = get_result(r2)
    assert result["status"] == "kept"
