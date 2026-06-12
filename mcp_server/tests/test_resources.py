"""Tests for new MCP resources — conventions and enhanced vocabulary/preferred.

Tests the three new/enhanced resources added last session:
  - omop://conventions/query-rules
  - omop://conventions/common-mistakes
  - omop://vocabulary/preferred (enhanced with concept_class_id column)

These are all static string resources (no database required).
"""

import pytest
import pytest_asyncio

from resources.omop_docs import register_resources


@pytest_asyncio.fixture(scope="module")
async def resource_server():
    """Register resources on a FastMCP instance."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("test-resources")
    register_resources(mcp)
    return mcp


# ---------------------------------------------------------------------------
# omop://conventions/query-rules
# ---------------------------------------------------------------------------


class TestQueryRulesResource:
    @pytest.mark.asyncio
    async def test_returns_content(self, resource_server):
        result = await resource_server.read_resource("omop://conventions/query-rules")
        text = str(result)
        assert len(text) > 100

    @pytest.mark.asyncio
    async def test_has_standard_concept_rules(self, resource_server):
        result = await resource_server.read_resource("omop://conventions/query-rules")
        text = str(result)
        assert "standard_concept" in text.lower() or "Standard Concept" in text

    @pytest.mark.asyncio
    async def test_has_anti_patterns(self, resource_server):
        result = await resource_server.read_resource("omop://conventions/query-rules")
        text = str(result)
        assert "Anti-Pattern" in text or "anti-pattern" in text or "Do NOT" in text

    @pytest.mark.asyncio
    async def test_has_join_conventions(self, resource_server):
        result = await resource_server.read_resource("omop://conventions/query-rules")
        text = str(result)
        assert "join" in text.lower() or "Join" in text

    @pytest.mark.asyncio
    async def test_has_temporal_conventions(self, resource_server):
        result = await resource_server.read_resource("omop://conventions/query-rules")
        text = str(result)
        assert "observation_period" in text


# ---------------------------------------------------------------------------
# omop://conventions/common-mistakes
# ---------------------------------------------------------------------------


class TestCommonMistakesResource:
    @pytest.mark.asyncio
    async def test_returns_content(self, resource_server):
        result = await resource_server.read_resource("omop://conventions/common-mistakes")
        text = str(result)
        assert len(text) > 100

    @pytest.mark.asyncio
    async def test_warns_about_hallucinated_ids(self, resource_server):
        result = await resource_server.read_resource("omop://conventions/common-mistakes")
        text = str(result)
        assert "hallucin" in text.lower() or "concept_id" in text

    @pytest.mark.asyncio
    async def test_warns_about_source_value(self, resource_server):
        result = await resource_server.read_resource("omop://conventions/common-mistakes")
        text = str(result)
        assert "source_value" in text

    @pytest.mark.asyncio
    async def test_warns_about_observation_period(self, resource_server):
        result = await resource_server.read_resource("omop://conventions/common-mistakes")
        text = str(result)
        assert "observation_period" in text or "observation period" in text

    @pytest.mark.asyncio
    async def test_warns_about_invalid_reason(self, resource_server):
        result = await resource_server.read_resource("omop://conventions/common-mistakes")
        text = str(result)
        assert "invalid_reason" in text

    @pytest.mark.asyncio
    async def test_warns_about_maps_to(self, resource_server):
        result = await resource_server.read_resource("omop://conventions/common-mistakes")
        text = str(result)
        assert "Maps to" in text

    @pytest.mark.asyncio
    async def test_has_numbered_sections(self, resource_server):
        result = await resource_server.read_resource("omop://conventions/common-mistakes")
        text = str(result)
        # Should have at least 5 numbered mistake sections
        assert "## 1." in text
        assert "## 5." in text


# ---------------------------------------------------------------------------
# omop://vocabulary/preferred (enhanced with concept_class_id)
# ---------------------------------------------------------------------------


class TestPreferredVocabulariesResource:
    @pytest.mark.asyncio
    async def test_returns_content(self, resource_server):
        result = await resource_server.read_resource("omop://vocabulary/preferred")
        text = str(result)
        assert len(text) > 100

    @pytest.mark.asyncio
    async def test_has_concept_class_id_column(self, resource_server):
        """Key enhancement from last session: concept_class_id column added."""
        result = await resource_server.read_resource("omop://vocabulary/preferred")
        text = str(result)
        assert "concept_class_id" in text

    @pytest.mark.asyncio
    async def test_has_preferred_mappings(self, resource_server):
        result = await resource_server.read_resource("omop://vocabulary/preferred")
        text = str(result)
        # Should have the key domain-vocabulary mappings
        assert "SNOMED" in text
        assert "RxNorm" in text
        assert "LOINC" in text

    @pytest.mark.asyncio
    async def test_has_domain_rows(self, resource_server):
        result = await resource_server.read_resource("omop://vocabulary/preferred")
        text = str(result)
        assert "Condition" in text
        assert "Drug" in text
        assert "Measurement" in text

    @pytest.mark.asyncio
    async def test_has_workflow_section(self, resource_server):
        result = await resource_server.read_resource("omop://vocabulary/preferred")
        text = str(result)
        assert "Workflow" in text or "workflow" in text
