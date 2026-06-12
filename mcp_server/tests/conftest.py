"""Shared fixtures for ohdsi-vocab MCP server tests."""

import sys
from pathlib import Path

import pytest

# Add mcp_server/ to sys.path so tool/resource imports work
_MCP_SERVER_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(_MCP_SERVER_DIR))


@pytest.fixture()
def reset_phenotype_cache():
    """Reset the phenotype library in-memory cache."""
    import tools.phenotype_library as pl
    original = pl._cohort_index
    pl._cohort_index = None
    yield
    pl._cohort_index = original


@pytest.fixture()
def reset_query_cache():
    """Reset the query library in-memory cache."""
    import tools.query_library as ql
    original = ql._query_index
    ql._query_index = None
    yield
    ql._query_index = original
