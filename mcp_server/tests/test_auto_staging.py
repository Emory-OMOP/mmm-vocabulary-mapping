"""Tests for auto-staging in concept-returning tools.

Verifies that each modified tool:
1. Stages concepts in the staging DB (result exists with correct concept_count)
2. Returns a result_id in the output string
3. Does NOT include concept_ids in the output string
"""

import os
import re
from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch

import pytest

from omop_vocab_core.staging import (
    get_result,
    get_result_concepts,
    init_staging_db,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def staging_db(tmp_path, monkeypatch):
    """Isolate staging DB per test."""
    db_path = str(tmp_path / "test_staging.duckdb")
    monkeypatch.setenv("CONCEPT_SET_STAGING_DB", db_path)
    init_staging_db()
    return db_path


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_ROWS = [
    {
        "concept_id": 201826,
        "concept_name": "Type 2 diabetes mellitus",
        "domain_id": "Condition",
        "vocabulary_id": "SNOMED",
        "concept_class_id": "Clinical Finding",
        "concept_code": "44054006",
        "standard_concept": "S",
        "invalid_reason": None,
    },
    {
        "concept_id": 4329847,
        "concept_name": "Diabetic neuropathy",
        "domain_id": "Condition",
        "vocabulary_id": "SNOMED",
        "concept_class_id": "Clinical Finding",
        "concept_code": "230572002",
        "standard_concept": "S",
        "invalid_reason": None,
    },
]

HIERARCHY_ROWS = [
    {
        "concept_id": 441840,
        "concept_name": "Clinical finding",
        "domain_id": "Condition",
        "vocabulary_id": "SNOMED",
        "concept_class_id": "Clinical Finding",
        "standard_concept": "S",
        "min_separation": 3,
        "max_separation": 5,
    },
]

RELATIONSHIP_ROWS = [
    {
        "relationship_id": "Maps to",
        "related_concept_id": 201826,
        "related_concept_name": "Type 2 diabetes mellitus",
        "domain_id": "Condition",
        "vocabulary_id": "SNOMED",
        "concept_class_id": "Clinical Finding",
        "concept_code": "44054006",
        "standard_concept": "S",
    },
]

CONCEPT_SET_ROWS = [
    {
        "concept_id": 201826,
        "concept_name": "Type 2 diabetes mellitus",
        "domain_id": "Condition",
        "vocabulary_id": "SNOMED",
        "concept_class_id": "Clinical Finding",
        "standard_concept": "S",
        "is_descendant": 0,
    },
    {
        "concept_id": 4329847,
        "concept_name": "Diabetic neuropathy",
        "domain_id": "Condition",
        "vocabulary_id": "SNOMED",
        "concept_class_id": "Clinical Finding",
        "standard_concept": "S",
        "is_descendant": 1,
    },
]

GROUNDING_RESULTS = [
    {
        "concept_id": 201826,
        "concept_name": "Type 2 diabetes mellitus",
        "domain_id": "Condition",
        "vocabulary_id": "SNOMED",
        "concept_class_id": "Clinical Finding",
        "standard_concept": "S",
        "concept_code": "44054006",
        "match_tier": "name",
        "relevance_score": 0.95,
    },
]

MAPPING_RESULT = {
    "source": {
        "concept_id": 45757370,
        "concept_name": "E11.9",
        "domain_id": "Condition",
        "vocabulary_id": "ICD10CM",
        "concept_class_id": "ICD10 code",
        "standard_concept": None,
    },
    "target": {
        "concept_id": 201826,
        "concept_name": "Type 2 diabetes mellitus",
        "domain_id": "Condition",
        "vocabulary_id": "SNOMED",
        "concept_class_id": "Clinical Finding",
        "standard_concept": "S",
    },
    "chain": [
        {
            "relationship_id": "Maps to",
            "concept": {
                "concept_id": 201826,
                "concept_name": "Type 2 diabetes mellitus",
                "domain_id": "Condition",
                "vocabulary_id": "SNOMED",
                "concept_class_id": "Clinical Finding",
                "standard_concept": "S",
            },
        }
    ],
    "hops": 1,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Matches numeric concept_ids (5+ digits) that appear as standalone values
# in table cells or JSON — avoids false positives on result_id (small ints)
_CONCEPT_ID_PATTERN = re.compile(
    r"""
    (?:concept_id|related_id|source_id|target_id|subject_id|object_id)  # column/key names
    |                                                                     # OR
    (?<!\w)(?:201826|4329847|441840|4193704|443238|45757370)(?!\w)        # known test concept_ids
    """,
    re.VERBOSE,
)


def assert_no_concept_ids(text: str):
    """Assert that no concept_id column names or known test concept_ids appear."""
    matches = _CONCEPT_ID_PATTERN.findall(text)
    assert not matches, f"Found concept_id references in output: {matches}"


def assert_has_result_id(text: str) -> int:
    """Assert result_id appears and return its value."""
    m = re.search(r"result_id:\s*(\d+)", text)
    assert m, f"No result_id found in output:\n{text[:200]}"
    return int(m.group(1))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@patch("tools.search_concepts.search_concepts_core", return_value=SAMPLE_ROWS)
async def test_search_concepts(mock_core):
    from tools.search_concepts import register_search_concepts
    mcp = MagicMock()
    tools = {}
    mcp.tool.return_value = lambda fn: tools.update({fn.__name__: fn}) or fn
    register_search_concepts(mcp)

    output = await tools["search_concepts"](keyword="diabetes")
    assert_no_concept_ids(output)
    rid = assert_has_result_id(output)

    result = get_result(rid)
    assert result["concept_count"] == 2
    assert result["tool_name"] == "search_concepts"

    concepts = get_result_concepts(rid, include_concept_ids=True)
    assert concepts[0]["concept_id"] == 201826


@pytest.mark.asyncio
@patch("tools.concept_lookup.get_concept_core", return_value=SAMPLE_ROWS)
async def test_get_concept(mock_core):
    from tools.concept_lookup import register_concept_lookup
    mcp = MagicMock()
    tools = {}
    mcp.tool.return_value = lambda fn: tools.update({fn.__name__: fn}) or fn
    register_concept_lookup(mcp)

    output = await tools["get_concept"](concept_ids=[201826, 4329847])
    assert_no_concept_ids(output)
    rid = assert_has_result_id(output)

    result = get_result(rid)
    assert result["concept_count"] == 2


@pytest.mark.asyncio
@patch("tools.concept_hierarchy.get_ancestors_core", return_value=(HIERARCHY_ROWS, "Type 2 diabetes"))
async def test_get_concept_ancestors(mock_core):
    from tools.concept_hierarchy import register_hierarchy_tools
    mcp = MagicMock()
    tools = {}
    mcp.tool.return_value = lambda fn: tools.update({fn.__name__: fn}) or fn
    register_hierarchy_tools(mcp)

    output = await tools["get_concept_ancestors"](concept_id=201826)
    assert_no_concept_ids(output)
    rid = assert_has_result_id(output)
    assert get_result(rid)["concept_count"] == 1


@pytest.mark.asyncio
@patch("tools.concept_hierarchy.get_descendants_core", return_value=(HIERARCHY_ROWS, "Diabetes"))
async def test_get_concept_descendants(mock_core):
    from tools.concept_hierarchy import register_hierarchy_tools
    mcp = MagicMock()
    tools = {}
    mcp.tool.return_value = lambda fn: tools.update({fn.__name__: fn}) or fn
    register_hierarchy_tools(mcp)

    output = await tools["get_concept_descendants"](concept_id=201826)
    assert_no_concept_ids(output)
    assert_has_result_id(output)


@pytest.mark.asyncio
@patch("tools.concept_set.preview_concept_set_core", return_value=(CONCEPT_SET_ROWS, 2))
async def test_preview_concept_set(mock_core):
    from tools.concept_set import register_concept_set_tools
    mcp = MagicMock()
    tools = {}
    mcp.tool.return_value = lambda fn: tools.update({fn.__name__: fn}) or fn
    register_concept_set_tools(mcp)

    output = await tools["preview_concept_set"](concept_ids=[201826])
    assert_no_concept_ids(output)
    rid = assert_has_result_id(output)

    result = get_result(rid)
    assert result["concept_count"] == 2

    concepts = get_result_concepts(rid, include_concept_ids=True)
    assert any(c.get("is_descendant") for c in concepts)


@pytest.mark.asyncio
@patch("tools.concept_set_resolver.resolve_concept_set_core")
async def test_resolve_concept_set(mock_core):
    mock_core.return_value = {
        "keyword": "diabetes",
        "input_concepts": SAMPLE_ROWS[:1],
        "resolved_set": CONCEPT_SET_ROWS,
        "total_count": 2,
        "include_descendants": True,
    }
    from tools.concept_set_resolver import register_concept_set_resolver_tools
    mcp = MagicMock()
    tools = {}
    mcp.tool.return_value = lambda fn: tools.update({fn.__name__: fn}) or fn
    register_concept_set_resolver_tools(mcp)

    output = await tools["resolve_concept_set"](keyword="diabetes")
    assert_no_concept_ids(output)
    rid = assert_has_result_id(output)
    assert get_result(rid)["concept_count"] == 2


@pytest.mark.asyncio
@patch("tools.concept_relationships.get_relationships_core")
async def test_get_concept_relationships(mock_core):
    mock_core.return_value = (RELATIONSHIP_ROWS, "E11.9", "ICD10CM")
    from tools.concept_relationships import register_relationship_tools
    mcp = MagicMock()
    tools = {}
    mcp.tool.return_value = lambda fn: tools.update({fn.__name__: fn}) or fn
    register_relationship_tools(mcp)

    output = await tools["get_concept_relationships"](concept_id=45757370)
    assert_no_concept_ids(output)
    rid = assert_has_result_id(output)

    concepts = get_result_concepts(rid, include_concept_ids=True)
    assert concepts[0]["concept_id"] == 201826


@pytest.mark.asyncio
@patch("tools.graph_exploration.graph_context")
@patch("tools.graph_exploration.explore_subgraph")
async def test_explore_concept_graph(mock_explore, mock_ctx):
    @dataclass
    class SubgraphResult:
        nodes: list = field(default_factory=list)
        edges: list = field(default_factory=list)
        depth: int = 2
        seed_ids: list = field(default_factory=list)
        truncated: bool = False

    mock_ctx.return_value.__enter__ = MagicMock()
    mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

    mock_explore.return_value = SubgraphResult(
        nodes=[
            {"concept_id": 201826, "concept_name": "Type 2 DM", "domain_id": "Condition",
             "vocabulary_id": "SNOMED", "concept_class_id": "Clinical Finding", "standard_concept": "S"},
            {"concept_id": 4329847, "concept_name": "Diabetic neuropathy", "domain_id": "Condition",
             "vocabulary_id": "SNOMED", "concept_class_id": "Clinical Finding", "standard_concept": "S"},
        ],
        edges=[
            {"source_id": 201826, "source_name": "Type 2 DM",
             "target_id": 4329847, "target_name": "Diabetic neuropathy",
             "relationship_name": "Is a"},
        ],
        seed_ids=[201826],
    )

    from tools.graph_exploration import register_exploration_tools
    mcp = MagicMock()
    tools = {}
    mcp.tool.return_value = lambda fn: tools.update({fn.__name__: fn}) or fn
    register_exploration_tools(mcp)

    output = await tools["explore_concept_graph"](concept_ids="201826")
    assert_no_concept_ids(output)
    rid = assert_has_result_id(output)
    assert get_result(rid)["concept_count"] == 2

    # Edges should use row indices, not concept_ids
    assert "#0" in output
    assert "#1" in output


@pytest.mark.asyncio
@patch("tools.graph_pathfinding.graph_context")
@patch("tools.graph_pathfinding.find_ranked_paths")
async def test_find_concept_paths(mock_paths, mock_ctx):
    @dataclass
    class PathProfile:
        hops: int = 1
        ontological_edges: int = 0
        mapping_edges: int = 1
        metadata_edges: int = 0
        vocab_switches: int = 1
        non_standard_concepts: int = 0
        invalid_concepts: int = 0

    @dataclass
    class PathExplanation:
        profile: PathProfile = field(default_factory=PathProfile)
        step_details: list = field(default_factory=list)

    ctx_mock = MagicMock()
    ctx_mock.concept_view.side_effect = lambda cid: {
        45757370: {"concept_name": "E11.9", "domain_id": "Condition",
                    "vocabulary_id": "ICD10CM", "concept_class_id": "ICD10 code",
                    "standard_concept": None},
        201826: {"concept_name": "Type 2 DM", "domain_id": "Condition",
                  "vocabulary_id": "SNOMED", "concept_class_id": "Clinical Finding",
                  "standard_concept": "S"},
    }.get(cid)

    mock_ctx.return_value.__enter__ = MagicMock(return_value=ctx_mock)
    mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

    mock_paths.return_value = [
        PathExplanation(
            step_details=[{
                "subject_id": 45757370, "subject_name": "E11.9", "subject_vocab": "ICD10CM",
                "predicate_name": "Maps to", "predicate_kind": "mapping",
                "object_id": 201826, "object_name": "Type 2 DM", "object_vocab": "SNOMED",
            }]
        ),
    ]

    from tools.graph_pathfinding import register_pathfinding_tools
    mcp = MagicMock()
    tools = {}
    mcp.tool.return_value = lambda fn: tools.update({fn.__name__: fn}) or fn
    register_pathfinding_tools(mcp)

    output = await tools["find_concept_paths"](
        source_concept_id=45757370, target_concept_id=201826,
    )
    assert_no_concept_ids(output)
    rid = assert_has_result_id(output)
    assert get_result(rid)["concept_count"] == 2


@pytest.mark.asyncio
@patch("tools.term_grounding.graph_context")
@patch("tools.term_grounding.ground_term", return_value=GROUNDING_RESULTS)
async def test_ground_clinical_term(mock_ground, mock_ctx):
    mock_ctx.return_value.__enter__ = MagicMock()
    mock_ctx.return_value.__exit__ = MagicMock(return_value=False)

    from tools.term_grounding import register_grounding_tools
    mcp = MagicMock()
    tools = {}
    mcp.tool.return_value = lambda fn: tools.update({fn.__name__: fn}) or fn
    register_grounding_tools(mcp)

    output = await tools["ground_clinical_term"](text="diabetes")
    assert_no_concept_ids(output)
    rid = assert_has_result_id(output)
    assert get_result(rid)["concept_count"] == 1

    # Match tier should be preserved in output
    assert "name" in output


@pytest.mark.asyncio
@patch("tools.standard_mapping.trace_standard_mapping_core", return_value=MAPPING_RESULT)
async def test_trace_standard_mapping(mock_core):
    from tools.standard_mapping import register_standard_mapping_tools
    mcp = MagicMock()
    tools = {}
    mcp.tool.return_value = lambda fn: tools.update({fn.__name__: fn}) or fn
    register_standard_mapping_tools(mcp)

    output = await tools["trace_standard_mapping"](concept_id=45757370)
    assert_no_concept_ids(output)
    rid = assert_has_result_id(output)

    # Should stage both source and target
    result = get_result(rid)
    assert result["concept_count"] == 2


@pytest.mark.asyncio
@patch("tools.search_concepts.search_concepts_core", return_value=[])
async def test_empty_results_have_result_id_none(mock_core):
    from tools.search_concepts import register_search_concepts
    mcp = MagicMock()
    tools = {}
    mcp.tool.return_value = lambda fn: tools.update({fn.__name__: fn}) or fn
    register_search_concepts(mcp)

    output = await tools["search_concepts"](keyword="xyznonexistent")
    assert "result_id: none" in output
    assert_no_concept_ids(output)
