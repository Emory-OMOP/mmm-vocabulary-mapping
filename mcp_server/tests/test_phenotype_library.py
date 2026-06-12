"""Tests for phenotype_library tools — search_phenotypes and get_phenotype.

Tests both the internal helper functions and the registered MCP tool functions.
Data source: mcp_server/data/phenotype_library/ (downloaded via download_phenotype_library.sh).
"""

import json

import pytest
import pytest_asyncio

from core.phenotype import (
    _COHORTS_CSV,
    _COHORTS_DIR,
    _DOMAIN_COLUMNS,
    format_domains,
    _load_index,
    _match_score,
)
from tools.phenotype_library import register_phenotype_library_tools

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def phenotype_index():
    """Load the phenotype index once for the test module."""
    return _load_index()


@pytest_asyncio.fixture(scope="module")
async def phenotype_tools():
    """Register phenotype tools on a FastMCP instance and return tool callables."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("test-phenotype")
    register_phenotype_library_tools(mcp)
    return mcp


# ---------------------------------------------------------------------------
# Data availability
# ---------------------------------------------------------------------------


class TestDataAvailability:
    def test_cohorts_csv_exists(self):
        assert _COHORTS_CSV.exists(), (
            f"Cohorts.csv not found at {_COHORTS_CSV}. "
            "Run scripts/download_phenotype_library.sh first."
        )

    def test_cohorts_dir_exists(self):
        assert _COHORTS_DIR.exists(), (
            f"cohorts/ directory not found at {_COHORTS_DIR}. "
            "Run scripts/download_phenotype_library.sh first."
        )

    def test_cohorts_dir_has_json_files(self):
        json_files = list(_COHORTS_DIR.glob("*.json"))
        assert len(json_files) > 100, (
            f"Expected 100+ cohort JSON files, found {len(json_files)}"
        )


# ---------------------------------------------------------------------------
# _load_index
# ---------------------------------------------------------------------------


class TestLoadIndex:
    def test_loads_nonempty_list(self, phenotype_index):
        assert len(phenotype_index) > 500, (
            f"Expected 500+ phenotype entries, got {len(phenotype_index)}"
        )

    def test_entries_have_required_fields(self, phenotype_index):
        required = {"cohortId", "cohortName", "status"}
        for entry in phenotype_index[:10]:
            assert required.issubset(entry.keys()), (
                f"Entry missing required fields: {required - entry.keys()}"
            )

    def test_cohort_id_is_int(self, phenotype_index):
        for entry in phenotype_index[:50]:
            assert isinstance(entry["cohortId"], int), (
                f"cohortId should be int, got {type(entry['cohortId'])}"
            )

    def test_bom_handling(self, phenotype_index):
        """Verify BOM/quoted-header CSV parsing — the first field should be 'cohortId', not BOM-prefixed."""
        first = phenotype_index[0]
        assert "cohortId" in first, (
            f"First entry keys: {list(first.keys())} — BOM may not be stripped"
        )

    def test_caching(self, phenotype_index):
        """Second call should return the same cached object."""
        second = _load_index()
        assert second is phenotype_index


# ---------------------------------------------------------------------------
# _match_score
# ---------------------------------------------------------------------------


class TestMatchScore:
    def test_exact_name_match(self):
        entry = {"cohortName": "Type 2 Diabetes Mellitus", "logicDescription": "", "hashTag": ""}
        score = _match_score(entry, "diabetes")
        assert score >= 10, f"Name match should score >= 10, got {score}"

    def test_word_boundary_bonus(self):
        entry = {"cohortName": "Diabetes Mellitus", "logicDescription": "", "hashTag": ""}
        score_boundary = _match_score(entry, "diabetes")
        entry2 = {"cohortName": "Prediabetes", "logicDescription": "", "hashTag": ""}
        score_no_boundary = _match_score(entry2, "diabetes")
        assert score_boundary > score_no_boundary, (
            f"Word-boundary match ({score_boundary}) should outscore mid-word ({score_no_boundary})"
        )

    def test_description_match(self):
        entry = {"cohortName": "Some Cohort", "logicDescription": "patients with diabetes", "hashTag": ""}
        score = _match_score(entry, "diabetes")
        assert score >= 5, f"Description match should score >= 5, got {score}"

    def test_tag_match(self):
        entry = {"cohortName": "Some Cohort", "logicDescription": "", "hashTag": "#diabetes"}
        score = _match_score(entry, "diabetes")
        assert score >= 3, f"Tag match should score >= 3, got {score}"

    def test_no_match_returns_zero(self):
        entry = {"cohortName": "Hypertension", "logicDescription": "blood pressure", "hashTag": "#cardio"}
        score = _match_score(entry, "xyznonexistent")
        assert score == 0

    def test_case_insensitive(self):
        entry = {"cohortName": "DIABETES MELLITUS", "logicDescription": "", "hashTag": ""}
        score = _match_score(entry, "diabetes")
        assert score >= 10


# ---------------------------------------------------------------------------
# format_domains
# ---------------------------------------------------------------------------


class TestFormatDomains:
    def test_single_domain(self):
        entry = {"domainConditionOccurrence": "1"}
        result = format_domains(entry)
        assert result == "condition"

    def test_multiple_domains(self):
        entry = {"domainConditionOccurrence": "1", "domainDrugExposure": "1"}
        result = format_domains(entry)
        assert "condition" in result
        assert "drug" in result

    def test_no_domains(self):
        entry = {}
        result = format_domains(entry)
        assert result == "none"

    def test_true_string_variants(self):
        """Domain flags may be '1', 'TRUE', or 'true'."""
        for val in ("1", "TRUE", "true", True):
            entry = {"domainMeasurement": val}
            result = format_domains(entry)
            assert "measurement" in result, f"Failed for value {val!r}"


# ---------------------------------------------------------------------------
# search_phenotypes (MCP tool)
# ---------------------------------------------------------------------------


class TestSearchPhenotypes:
    @pytest.mark.asyncio
    async def test_basic_search(self, phenotype_tools):
        result = await phenotype_tools.call_tool("search_phenotypes", {"keyword": "diabetes"})
        text = result[0][0].text
        assert "diabetes" in text.lower()
        assert "cohort_id" in text
        assert "| " in text  # markdown table

    @pytest.mark.asyncio
    async def test_domain_filter(self, phenotype_tools):
        result = await phenotype_tools.call_tool(
            "search_phenotypes",
            {"keyword": "diabetes", "domain": "condition"},
        )
        text = result[0][0].text
        assert "diabetes" in text.lower()

    @pytest.mark.asyncio
    async def test_status_filter(self, phenotype_tools):
        result = await phenotype_tools.call_tool(
            "search_phenotypes",
            {"keyword": "covid", "status": "Withdrawn"},
        )
        text = result[0][0].text
        # Should find results or say none found — either way no crash
        assert isinstance(text, str)
        assert len(text) > 0

    @pytest.mark.asyncio
    async def test_invalid_domain(self, phenotype_tools):
        result = await phenotype_tools.call_tool(
            "search_phenotypes",
            {"keyword": "diabetes", "domain": "invalid_domain"},
        )
        text = result[0][0].text
        assert "Unknown domain" in text

    @pytest.mark.asyncio
    async def test_no_results(self, phenotype_tools):
        result = await phenotype_tools.call_tool(
            "search_phenotypes",
            {"keyword": "xyznonexistent_term_12345"},
        )
        text = result[0][0].text
        assert "No phenotypes found" in text

    @pytest.mark.asyncio
    async def test_limit_respected(self, phenotype_tools):
        result = await phenotype_tools.call_tool(
            "search_phenotypes",
            {"keyword": "diabetes", "limit": 3},
        )
        text = result[0][0].text
        # Count data rows (exclude header row and separator)
        table_rows = [
            line for line in text.splitlines()
            if line.startswith("| ") and not line.startswith("| cohort_id") and not line.startswith("|:")
        ]
        assert len(table_rows) <= 3, f"Expected <= 3 rows, got {len(table_rows)}"

    @pytest.mark.asyncio
    async def test_limit_clamped_to_max(self, phenotype_tools):
        """Limit should be clamped to 30 max."""
        result = await phenotype_tools.call_tool(
            "search_phenotypes",
            {"keyword": "diabetes", "limit": 100},
        )
        text = result[0][0].text
        table_rows = [
            line for line in text.splitlines()
            if line.startswith("| ") and not line.startswith("| cohort_id") and not line.startswith("|:")
        ]
        assert len(table_rows) <= 30


# ---------------------------------------------------------------------------
# get_phenotype (MCP tool)
# ---------------------------------------------------------------------------


class TestGetPhenotype:
    @pytest.mark.asyncio
    async def test_valid_cohort(self, phenotype_tools):
        """Cohort 10 should exist (we verified the JSON file)."""
        result = await phenotype_tools.call_tool("get_phenotype", {"cohort_id": 10})
        text = result[0][0].text
        assert "## Phenotype:" in text
        assert "```json" in text
        # Verify the JSON block is valid
        json_start = text.index("```json") + len("```json")
        json_end = text.index("```", json_start)
        cohort_json = text[json_start:json_end].strip()
        parsed = json.loads(cohort_json)
        assert "PrimaryCriteria" in parsed or "ConceptSets" in parsed or "cdmVersionRange" in parsed

    @pytest.mark.asyncio
    async def test_includes_metadata(self, phenotype_tools):
        result = await phenotype_tools.call_tool("get_phenotype", {"cohort_id": 10})
        text = result[0][0].text
        # Should include status and domains
        assert "**Status**:" in text or "**Domains**:" in text

    @pytest.mark.asyncio
    async def test_invalid_cohort(self, phenotype_tools):
        result = await phenotype_tools.call_tool("get_phenotype", {"cohort_id": 999999})
        text = result[0][0].text
        assert "not found" in text.lower()

    @pytest.mark.asyncio
    async def test_search_then_get_roundtrip(self, phenotype_tools):
        """Search for a phenotype, then retrieve it by ID."""
        search_result = await phenotype_tools.call_tool(
            "search_phenotypes",
            {"keyword": "hypertension", "limit": 1},
        )
        search_text = search_result[0][0].text
        # Extract first cohort_id from the table
        for line in search_text.splitlines():
            if line.startswith("| ") and not line.startswith("| cohort_id") and not line.startswith("|:"):
                cohort_id = int(line.split("|")[1].strip())
                break
        else:
            pytest.skip("No hypertension phenotypes found in search")

        get_result = await phenotype_tools.call_tool(
            "get_phenotype",
            {"cohort_id": cohort_id},
        )
        get_text = get_result[0][0].text
        assert "```json" in get_text
