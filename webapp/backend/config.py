"""Application settings from environment variables."""

from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuration loaded from environment variables."""

    # Database
    duckdb_path: str = str(Path(__file__).parent.parent.parent / "omop_vocab.duckdb")
    duckdb_vocab_schema: str = "main_vocab"
    duckdb_cdm_schema: str = "main_cdm"

    # Auth
    beta_passkey: str = "changeme"
    jwt_secret: str = "changeme-jwt-secret"
    jwt_algorithm: str = "HS256"
    jwt_expiry_days: int = 30

    # LLM Providers
    default_provider: str = "claude"
    default_model: str = "claude-sonnet-4-20250514"
    anthropic_api_key: str = ""
    ollama_base_url: str = "http://localhost:11434"
    openai_api_key: str = ""
    gemini_api_key: str = ""
    deepseek_api_key: str = ""

    # Agent
    max_tool_rounds: int = 50

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173", "http://localhost:9000", "http://localhost:10000"]

    # MCP servers (streamable HTTP URLs). This extract ships two servers:
    # ohdsi-vocab (Layer 1 retrieval/grounding) and omcp (read-only OMOP SQL —
    # the Select_Query / Get_Information_Schema tools the winning run used).
    mcp_ohdsi_vocab_url: str = "http://localhost:8001/mcp"
    mcp_omcp_url: str = "http://localhost:8003/mcp"

    # When False, hide Select_Query and Get_Information_Schema from the LLM
    # to prevent bypassing the CIRCE compilation pipeline for cohort queries.
    allow_raw_sql: bool = True

    # Session storage
    sessions_db_path: str = str(Path(__file__).parent.parent / "data" / "sessions.db")

    # Langfuse observability
    langfuse_enabled: bool = False
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3000"

    # Generic default system prompt for the agent. For the MMM vocabulary-mapping
    # run this is OVERRIDDEN at launch via the SYSTEM_PROMPT env var with the
    # task-specific prompt in mmm_pipeline/scripts/system_prompt.py. It describes
    # only the tools this repo actually ships: the ohdsi-vocab vocabulary/grounding
    # tools and the omcp read-only SQL tools.
    system_prompt: str = (
        "You are an OHDSI vocabulary assistant with access to OMOP vocabulary "
        "search and grounding tools plus a read-only SQL tool.\n\n"
        "## Database\n"
        "DuckDB containing the OMOP Standardized Vocabularies in a `main_vocab` "
        "schema: concept, concept_ancestor, concept_relationship, concept_synonym, "
        "concept_class, drug_strength, domain, vocabulary, relationship.\n"
        "Always schema-qualify tables, e.g. main_vocab.concept.\n\n"
        "## Tools\n"
        "Vocabulary lookup & grounding:\n"
        "- search_concepts: Find concepts by name, code, or keyword.\n"
        "- get_concept: Look up a single concept by concept_id.\n"
        "- get_concept_ancestors / get_concept_descendants: Navigate the hierarchy.\n"
        "- get_concept_relationships: Find related concepts (Maps to, Is a, etc).\n"
        "- ground_clinical_term: Resolve free text to Standard concepts (ILIKE → "
        "synonym → SapBERT embedding + hybrid re-rank).\n"
        "- standard_via_nonstandard: Match source-vocabulary text to non-standard "
        "concepts, then follow 'Maps to' to Standard targets.\n"
        "- get_table_schema: Column names and types for a vocabulary table.\n\n"
        "Result staging:\n"
        "- reveal_concept_ids: Surface the concept_ids for a staged result.\n"
        "- keep_result: Promote a staged result to a named, persistent draft.\n\n"
        "SQL (read-only):\n"
        "- Select_Query: Execute a read-only SELECT against the database.\n"
        "- Get_Information_Schema: View available tables and columns.\n\n"
        "## Workflow\n"
        "1. Use the vocabulary tools to find concept_ids — never guess IDs.\n"
        "2. Schema-qualify SQL (main_vocab.concept). Use Select_Query for ad-hoc "
        "vocabulary lookups the retrieval tools can't express.\n"
        "3. Always cite concept_ids from tool results."
    )

    model_config = {"env_prefix": "", "case_sensitive": False}


settings = Settings()
