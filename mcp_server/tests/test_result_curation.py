"""Tests for result curation tools."""

import json
import os

import pytest

from omop_vocab_core import staging


@pytest.fixture(autouse=True)
def isolated_staging_db(tmp_path):
    """Use a temporary staging DB for each test."""
    db_path = str(tmp_path / "test_staging.duckdb")
    os.environ["CONCEPT_SET_STAGING_DB"] = db_path
    staging.init_staging_db()
    yield db_path
    os.environ.pop("CONCEPT_SET_STAGING_DB", None)


def _seed_result(tool_name: str = "search_concepts", concepts: list[dict] | None = None) -> int:
    """Create a result with sample concepts and return its result_id."""
    if concepts is None:
        concepts = [
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
            },
            {
                "concept_id": 443238,
                "concept_name": "Diabetic neuropathy",
                "domain_id": "Condition",
                "vocabulary_id": "SNOMED",
                "concept_class_id": "Clinical Finding",
                "concept_code": "230572002",
                "standard_concept": "S",
            },
        ]
    result_id = staging.create_result(tool_name=tool_name, parameters={"keyword": "diabetes"})
    staging.add_result_concepts(result_id, concepts)
    return result_id


class TestCherryPick:
    def test_creates_child_with_subset(self):
        parent_id = _seed_result()
        child_id = staging.cherry_pick(parent_id, [0, 2])

        child_concepts = staging.get_result_concepts(child_id, include_concept_ids=True)
        assert len(child_concepts) == 2
        assert child_concepts[0]["concept_id"] == 201826
        assert child_concepts[1]["concept_id"] == 443238

    def test_child_has_correct_parent(self):
        parent_id = _seed_result()
        child_id = staging.cherry_pick(parent_id, [1])

        child_result = staging.get_result(child_id)
        assert child_result["parent_result_id"] == parent_id
        assert child_result["tool_name"] == "cherry_pick"

    def test_reindexes_from_zero(self):
        parent_id = _seed_result()
        child_id = staging.cherry_pick(parent_id, [2])

        child_concepts = staging.get_result_concepts(child_id)
        assert child_concepts[0]["row_index"] == 0


class TestExclude:
    def test_marks_matching_concepts_excluded(self):
        parent_id = _seed_result()

        # Simulate exclude_from_result logic
        parent_concepts = staging.get_result_concepts(parent_id, include_concept_ids=True)
        keyword = "neuropathy"
        child_concepts = []
        excluded_count = 0
        for c in parent_concepts:
            c_copy = dict(c)
            c_copy.pop("result_id", None)
            c_copy.pop("row_index", None)
            if keyword.lower() in (c_copy.get("concept_name") or "").lower():
                c_copy["is_excluded"] = True
                excluded_count += 1
            child_concepts.append(c_copy)

        child_id = staging.create_result(
            tool_name="exclude",
            parameters={"keyword": keyword},
            parent_result_id=parent_id,
        )
        staging.add_result_concepts(child_id, child_concepts)

        result_concepts = staging.get_result_concepts(child_id, include_concept_ids=True)
        assert len(result_concepts) == 3  # all concepts present
        assert excluded_count == 1

        excluded = [c for c in result_concepts if c["is_excluded"]]
        assert len(excluded) == 1
        assert excluded[0]["concept_id"] == 443238

    def test_case_insensitive_match(self):
        parent_id = _seed_result()
        parent_concepts = staging.get_result_concepts(parent_id, include_concept_ids=True)

        keyword = "DIABETES"
        excluded_count = sum(
            1 for c in parent_concepts
            if keyword.lower() in (c.get("concept_name") or "").lower()
        )
        assert excluded_count == 2  # matches 2 of 3 concepts


class TestModifyFlags:
    def test_updates_flags_on_specified_indices(self):
        parent_id = _seed_result()
        parent_concepts = staging.get_result_concepts(parent_id, include_concept_ids=True)

        idx_set = {0, 1}
        child_concepts = []
        for c in parent_concepts:
            c_copy = dict(c)
            orig_index = c_copy.pop("row_index")
            c_copy.pop("result_id", None)
            if orig_index in idx_set:
                c_copy["include_descendants"] = True
            child_concepts.append(c_copy)

        child_id = staging.create_result(
            tool_name="modify_flags",
            parameters={"indices": list(idx_set), "include_descendants": True},
            parent_result_id=parent_id,
        )
        staging.add_result_concepts(child_id, child_concepts)

        result = staging.get_result_concepts(child_id)
        assert result[0]["include_descendants"] is True
        assert result[1]["include_descendants"] is True
        assert result[2]["include_descendants"] is False  # unchanged

    def test_preserves_unspecified_flags(self):
        concepts = [
            {
                "concept_id": 201826,
                "concept_name": "T2DM",
                "domain_id": "Condition",
                "vocabulary_id": "SNOMED",
                "include_descendants": True,
                "is_excluded": False,
                "include_mapped": True,
            },
        ]
        parent_id = _seed_result(concepts=concepts)
        parent_concepts = staging.get_result_concepts(parent_id, include_concept_ids=True)

        child_concepts = []
        for c in parent_concepts:
            c_copy = dict(c)
            c_copy.pop("row_index", None)
            c_copy.pop("result_id", None)
            c_copy["is_excluded"] = True  # only modify is_excluded
            child_concepts.append(c_copy)

        child_id = staging.create_result(
            tool_name="modify_flags",
            parent_result_id=parent_id,
        )
        staging.add_result_concepts(child_id, child_concepts)

        result = staging.get_result_concepts(child_id)
        assert result[0]["is_excluded"] is True
        assert result[0]["include_descendants"] is True  # preserved
        assert result[0]["include_mapped"] is True  # preserved


class TestKeepResult:
    def test_promotes_to_draft(self):
        result_id = _seed_result()
        staging.promote_result(result_id, "Type 2 Diabetes")

        result = staging.get_result(result_id)
        assert result["status"] == "kept"
        assert result["draft_name"] == "Type 2 Diabetes"

    def test_appears_in_drafts_list(self):
        result_id = _seed_result()
        staging.promote_result(result_id, "My Draft")

        drafts = staging.list_drafts()
        assert len(drafts) == 1
        assert drafts[0]["draft_name"] == "My Draft"


class TestReviewResults:
    def test_list_all_results(self):
        _seed_result()
        _seed_result(tool_name="get_concept")

        results = staging.list_results()
        assert len(results) == 2

    def test_single_result_detail(self):
        result_id = _seed_result()
        result = staging.get_result(result_id)
        concepts = staging.get_result_concepts(result_id)

        assert result["tool_name"] == "search_concepts"
        assert result["concept_count"] == 3
        assert len(concepts) == 3

    def test_empty_results(self):
        results = staging.list_results()
        assert results == []


class TestReviewDrafts:
    def test_no_drafts_initially(self):
        drafts = staging.list_drafts()
        assert drafts == []

    def test_drafts_after_promote(self):
        r1 = _seed_result()
        r2 = _seed_result(tool_name="get_concept")
        staging.promote_result(r1, "Draft A")
        staging.promote_result(r2, "Draft B")

        drafts = staging.list_drafts()
        assert len(drafts) == 2
        names = {d["draft_name"] for d in drafts}
        assert names == {"Draft A", "Draft B"}


class TestResultLineage:
    def test_single_step(self):
        result_id = _seed_result()
        chain = staging.get_result_lineage(result_id)
        assert len(chain) == 1
        assert chain[0]["result_id"] == result_id

    def test_multi_step_chain(self):
        parent_id = _seed_result()
        child_id = staging.cherry_pick(parent_id, [0, 1])
        grandchild_id = staging.cherry_pick(child_id, [0])

        chain = staging.get_result_lineage(grandchild_id)
        assert len(chain) == 3
        ids = [step["result_id"] for step in chain]
        assert ids == sorted(ids)  # ordered root → leaf


class TestRevealConceptIds:
    def test_includes_concept_ids(self):
        result_id = _seed_result()
        concepts = staging.get_result_concepts(result_id, include_concept_ids=True)

        assert all("concept_id" in c for c in concepts)
        assert concepts[0]["concept_id"] == 201826

    def test_without_ids_strips_them(self):
        result_id = _seed_result()
        concepts = staging.get_result_concepts(result_id, include_concept_ids=False)

        assert all("concept_id" not in c for c in concepts)
