"""Tests for query_library tools — search_query_patterns and get_query.

Tests both the internal helper functions and the registered MCP tool functions.
Data source: mcp_server/data/query_library/ (downloaded via download_query_library.sh).
"""

from pathlib import Path

import pytest
import pytest_asyncio

from core.query_library import (
    _DATA_DIR,
    _extract_query_id,
    _load_index,
    _match_score,
    _parse_metadata,
    _parse_query_file,
    _parse_section,
    _parse_sql,
)
from tools.query_library import register_query_library_tools

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def query_index():
    """Load the query index once for the test module."""
    return _load_index()


@pytest_asyncio.fixture(scope="module")
async def query_tools():
    """Register query library tools on a FastMCP instance."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("test-query-library")
    register_query_library_tools(mcp)
    return mcp


# ---------------------------------------------------------------------------
# Sample markdown for parser tests
# ---------------------------------------------------------------------------

SAMPLE_QUERY_MD = """\
<!---
Group:drug
Name:D01 Find drug concept by concept ID
Author:Patrick Ryan
CDM Version: 5.3
-->

# D01: Find drug concept by concept ID

## Description
This is the lookup for obtaining drug concept details.

## Query
```sql
SELECT c.concept_id, c.concept_name
FROM @vocab.concept AS c
WHERE c.concept_id = 1545999;
```

## Input

| Parameter | Example | Mandatory | Notes |
| --- | --- | --- | --- |
| Concept ID | 1545999 | Yes | RxNorm concept |

## Output

| Field | Description |
| --- | --- |
| concept_id | Concept Identifier |
| concept_name | Name of the concept |
"""

# ---------------------------------------------------------------------------
# Data availability
# ---------------------------------------------------------------------------


class TestDataAvailability:
    def test_data_dir_exists(self):
        assert _DATA_DIR.exists(), (
            f"QueryLibrary data not found at {_DATA_DIR}. "
            "Run scripts/download_query_library.sh first."
        )

    def test_has_markdown_files(self):
        md_files = list(_DATA_DIR.rglob("*.md"))
        assert len(md_files) > 100, (
            f"Expected 100+ query markdown files, found {len(md_files)}"
        )

    def test_has_category_directories(self):
        subdirs = [d.name for d in _DATA_DIR.iterdir() if d.is_dir()]
        assert "drug" in subdirs, f"Expected 'drug' category dir, found: {subdirs}"
        assert "condition" in subdirs or "condition_era" in subdirs


# ---------------------------------------------------------------------------
# _parse_metadata
# ---------------------------------------------------------------------------


class TestParseMetadata:
    def test_basic_parsing(self):
        meta = _parse_metadata(SAMPLE_QUERY_MD)
        assert meta["group"] == "drug"
        assert meta["name"] == "D01 Find drug concept by concept ID"
        assert meta["author"] == "Patrick Ryan"
        assert meta["cdm version"] == "5.3"

    def test_empty_input(self):
        assert _parse_metadata("") == {}

    def test_no_comment_block(self):
        assert _parse_metadata("# Just a heading\nSome text.") == {}

    def test_missing_fields(self):
        text = "<!---\nGroup:drug\n-->"
        meta = _parse_metadata(text)
        assert meta["group"] == "drug"
        assert "name" not in meta


# ---------------------------------------------------------------------------
# _parse_sql
# ---------------------------------------------------------------------------


class TestParseSql:
    def test_extracts_sql_block(self):
        sql = _parse_sql(SAMPLE_QUERY_MD)
        assert "SELECT c.concept_id" in sql
        assert "@vocab.concept" in sql
        assert "1545999" in sql

    def test_no_sql_block(self):
        assert _parse_sql("No SQL here") == ""

    def test_strips_fence_markers(self):
        sql = _parse_sql(SAMPLE_QUERY_MD)
        assert "```" not in sql


# ---------------------------------------------------------------------------
# _parse_section
# ---------------------------------------------------------------------------


class TestParseSection:
    def test_extracts_description(self):
        desc = _parse_section(SAMPLE_QUERY_MD, "Description")
        assert "drug concept details" in desc

    def test_extracts_input(self):
        inp = _parse_section(SAMPLE_QUERY_MD, "Input")
        assert "Concept ID" in inp

    def test_extracts_output(self):
        out = _parse_section(SAMPLE_QUERY_MD, "Output")
        assert "concept_name" in out

    def test_missing_section(self):
        result = _parse_section(SAMPLE_QUERY_MD, "Nonexistent")
        assert result == ""


# ---------------------------------------------------------------------------
# _extract_query_id
# ---------------------------------------------------------------------------


class TestExtractQueryId:
    def test_drug_query(self):
        assert _extract_query_id("D01 Find drug concept") == "D01"

    def test_condition_era(self):
        assert _extract_query_id("CE05 Conditions with era length") == "CE05"

    def test_multi_letter_prefix(self):
        assert _extract_query_id("DER18 Some drug era query") == "DER18"

    def test_no_prefix(self):
        assert _extract_query_id("Some query without prefix") == ""


# ---------------------------------------------------------------------------
# _parse_query_file
# ---------------------------------------------------------------------------


class TestParseQueryFile:
    def test_parses_real_file(self):
        """Parse the actual D01.md file from downloaded data."""
        d01_path = _DATA_DIR / "drug" / "D01.md"
        if not d01_path.exists():
            pytest.skip("D01.md not found in query library data")

        result = _parse_query_file(d01_path)
        assert result is not None
        assert result["query_id"] == "D01"
        assert "drug" in result["group"].lower()
        assert len(result["sql"]) > 0
        assert result["name"]  # display name should be non-empty

    def test_returns_none_for_missing_file(self):
        result = _parse_query_file(Path("/nonexistent/file.md"))
        assert result is None


# ---------------------------------------------------------------------------
# _load_index
# ---------------------------------------------------------------------------


class TestLoadIndex:
    def test_loads_nonempty_list(self, query_index):
        assert len(query_index) > 100, (
            f"Expected 100+ query entries, got {len(query_index)}"
        )

    def test_entries_have_required_fields(self, query_index):
        required = {"query_id", "name", "full_name", "group", "sql", "file"}
        for entry in query_index[:10]:
            assert required.issubset(entry.keys()), (
                f"Entry missing required fields: {required - entry.keys()}"
            )

    def test_entries_have_sql(self, query_index):
        with_sql = [e for e in query_index if e["sql"]]
        assert len(with_sql) > 50, (
            f"Expected 50+ entries with SQL, got {len(with_sql)}"
        )

    def test_caching(self, query_index):
        second = _load_index()
        assert second is query_index


# ---------------------------------------------------------------------------
# _match_score
# ---------------------------------------------------------------------------


class TestMatchScore:
    def test_name_match(self):
        entry = {"full_name": "D01 Find drug concept by ID", "description": "", "group": ""}
        score = _match_score(entry, "drug")
        assert score >= 10

    def test_description_match(self):
        entry = {"full_name": "D01 Some query", "description": "finds drug concepts", "group": ""}
        score = _match_score(entry, "drug")
        assert score >= 5

    def test_group_match(self):
        entry = {"full_name": "D01 Some query", "description": "", "group": "drug"}
        score = _match_score(entry, "drug")
        assert score >= 3

    def test_no_match(self):
        entry = {"full_name": "D01 Find concept", "description": "concept lookup", "group": "drug"}
        score = _match_score(entry, "xyznonexistent")
        assert score == 0


# ---------------------------------------------------------------------------
# search_query_patterns (MCP tool)
# ---------------------------------------------------------------------------


class TestSearchQueryPatterns:
    @pytest.mark.asyncio
    async def test_basic_search(self, query_tools):
        result = await query_tools.call_tool("search_query_patterns", {"keyword": "drug"})
        text = result[0][0].text
        assert "drug" in text.lower()
        assert "query_id" in text
        assert "| " in text  # markdown table

    @pytest.mark.asyncio
    async def test_category_filter(self, query_tools):
        result = await query_tools.call_tool(
            "search_query_patterns",
            {"keyword": "concept", "category": "drug"},
        )
        text = result[0][0].text
        assert isinstance(text, str)
        assert len(text) > 0

    @pytest.mark.asyncio
    async def test_no_results(self, query_tools):
        result = await query_tools.call_tool(
            "search_query_patterns",
            {"keyword": "xyznonexistent_query_12345"},
        )
        text = result[0][0].text
        assert "No query patterns found" in text

    @pytest.mark.asyncio
    async def test_limit_respected(self, query_tools):
        result = await query_tools.call_tool(
            "search_query_patterns",
            {"keyword": "drug", "limit": 3},
        )
        text = result[0][0].text
        table_rows = [
            line for line in text.splitlines()
            if line.startswith("| ") and not line.startswith("| query_id") and not line.startswith("|:")
        ]
        assert len(table_rows) <= 3

    @pytest.mark.asyncio
    async def test_limit_clamped_to_max(self, query_tools):
        result = await query_tools.call_tool(
            "search_query_patterns",
            {"keyword": "concept", "limit": 100},
        )
        text = result[0][0].text
        table_rows = [
            line for line in text.splitlines()
            if line.startswith("| ") and not line.startswith("| query_id") and not line.startswith("|:")
        ]
        assert len(table_rows) <= 20


# ---------------------------------------------------------------------------
# get_query (MCP tool)
# ---------------------------------------------------------------------------


class TestGetQuery:
    @pytest.mark.asyncio
    async def test_valid_query(self, query_tools):
        result = await query_tools.call_tool("get_query", {"query_id": "D01"})
        text = result[0][0].text
        assert "D01" in text
        assert "```sql" in text
        assert "SELECT" in text
        assert "@vocab" in text or "@cdm" in text

    @pytest.mark.asyncio
    async def test_case_insensitive_id(self, query_tools):
        result = await query_tools.call_tool("get_query", {"query_id": "d01"})
        text = result[0][0].text
        assert "D01" in text
        assert "```sql" in text

    @pytest.mark.asyncio
    async def test_includes_metadata(self, query_tools):
        result = await query_tools.call_tool("get_query", {"query_id": "D01"})
        text = result[0][0].text
        assert "**Category**:" in text or "**Author**:" in text

    @pytest.mark.asyncio
    async def test_invalid_query(self, query_tools):
        result = await query_tools.call_tool("get_query", {"query_id": "ZZZ99"})
        text = result[0][0].text
        assert "not found" in text.lower()

    @pytest.mark.asyncio
    async def test_search_then_get_roundtrip(self, query_tools):
        """Search for a query, then retrieve it by ID."""
        search_result = await query_tools.call_tool(
            "search_query_patterns",
            {"keyword": "condition", "limit": 1},
        )
        search_text = search_result[0][0].text
        # Extract first query_id from the table
        for line in search_text.splitlines():
            if line.startswith("| ") and not line.startswith("| query_id") and not line.startswith("|:"):
                query_id = line.split("|")[1].strip()
                break
        else:
            pytest.skip("No condition queries found in search")

        get_result = await query_tools.call_tool("get_query", {"query_id": query_id})
        get_text = get_result[0][0].text
        assert "```sql" in get_text or "not found" not in get_text.lower()
