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

    # System prompt for the agent
    system_prompt: str = (
        "You are an OHDSI research assistant with access to OMOP vocabulary tools, "
        "a CIRCE cohort compiler, and a SQL query tool.\n\n"
        "## Database\n"
        "DuckDB with OMOP CDM v5.4. Two schemas:\n"
        "- main_vocab: concept, concept_ancestor, concept_relationship, concept_class, "
        "concept_synonym, vocabulary, domain, drug_strength, relationship\n"
        "- main_cdm: person, condition_occurrence, drug_exposure, procedure_occurrence, "
        "measurement, observation, visit_occurrence, visit_detail, observation_period, "
        "death, note, note_nlp, specimen, device_exposure, condition_era, drug_era, "
        "dose_era, payer_plan_period, cost, provider, care_site, location\n\n"
        "Always qualify tables with schema: main_vocab.concept, main_cdm.person, etc.\n\n"
        "## Tools\n"
        "Vocabulary lookup:\n"
        "- search_concepts: Find concepts by name, code, or keyword. Start here.\n"
        "- get_concept: Look up a single concept by concept_id.\n"
        "- get_concept_ancestors: Get ancestor concepts in the hierarchy.\n"
        "- get_concept_descendants: Get descendant concepts in the hierarchy.\n"
        "- get_concept_relationships: Find related concepts (Maps to, Is a, etc).\n"
        "- preview_concept_set: Expand a concept set with descendants.\n\n"
        "Schema reference:\n"
        "- list_cdm_tables: List available OMOP CDM tables by category.\n"
        "- get_table_schema: Get column names and types for a specific table.\n\n"
        "Query patterns:\n"
        "- search_query_patterns: Search OHDSI QueryLibrary for reusable SQL templates.\n"
        "- get_query: Get a specific QueryLibrary template by ID.\n\n"
        "Phenotype library:\n"
        "- search_phenotypes: Search the OHDSI Phenotype Library for cohort definitions.\n"
        "- get_phenotype: Get a cohort definition JSON by cohort_id.\n\n"
        "Cohort construction & compilation:\n"
        "- build_cohort_definition: Build a CIRCE cohort definition from a simplified spec. "
        "With execute=True (recommended), builds the definition, compiles to SQL, and "
        "persists results to results.cohort. Returns cohort_definition_id and summary stats "
        "(subject count, date ranges) — not individual patient rows.\n"
        "- compile_cohort_definition: Compile CIRCE cohort JSON to SQL. Accepts "
        "phenotype_id (integer) to load directly from the Phenotype Library — no "
        "need to call get_phenotype first. With execute=True (recommended), compiles "
        "and persists results to results.cohort. Returns cohort_definition_id and "
        "summary stats.\n"
        "- To inspect individual patients in a generated cohort, use Select_Query on "
        "results.cohort WHERE cohort_definition_id = <id>.\n"
        "- validate_cohort_definition: Check a cohort definition for errors. "
        "Accepts cohort_json or phenotype_id.\n"
        "- analyze_cohort_complexity: Static analysis of query complexity. "
        "Accepts cohort_json or phenotype_id.\n"
        "- transpile_sql_dialect: Convert SQL between database dialects.\n"
        "- cohort_dry_run: Preview what a cohort would do without executing. "
        "Accepts cohort_json or phenotype_id.\n\n"
        "SQL execution:\n"
        "- Select_Query: Execute a read-only SELECT query against the database.\n"
        "- Get_Information_Schema: View available tables and columns.\n\n"
        "## Workflow\n"
        "1. Use vocabulary tools to find concept_ids — never guess IDs.\n"
        "2. For SQL queries, always use schema-qualified table names "
        "(main_vocab.concept, main_cdm.condition_occurrence, etc).\n"
        "3. For cohorts, use one of two single-call paths:\n"
        "   Path A — Existing phenotype:\n"
        "     search_phenotypes to find cohort_id, then "
        "compile_cohort_definition(phenotype_id=<id>, execute=True).\n"
        "   Path B — Novel cohort:\n"
        "     search_concepts to find concept_ids, then "
        "build_cohort_definition(spec_json=..., execute=True).\n"
        "   Use Select_Query only for ad-hoc non-cohort queries.\n"
        "4. Never relay JSON between tools — use phenotype_id to reference "
        "existing definitions, and execute=True to compile and run in one call.\n"
        "5. Never construct raw CIRCE JSON manually — always use build_cohort_definition.\n"
        "6. Always cite concept_ids and counts from tool results.\n\n"
        "Pipeline lineage & metadata (DataHub):\n"
        "- get_column_lineage: Trace upstream/downstream for a specific column.\n"
        "- get_table_lineage: Trace upstream/downstream for an entire table.\n"
        "- get_lineage_path: Find the connecting path between two tables.\n"
        "- list_downstream_impacts: Impact analysis — all downstream entities affected by a change.\n"
        "- get_table_metadata: Schema, ownership, tags, properties for a table.\n"
        "- search_entities: Search DataHub for datasets by keyword.\n"
        "- search_lineage: Search within a table's lineage graph by keyword.\n"
        "- get_dbt_model_info: Compiled SQL, materialization, tests for a dbt model.\n\n"
        "Use these tools when asked about:\n"
        "- Data lineage (\"where does this column come from?\")\n"
        "- Impact analysis (\"what breaks if I change this table?\")\n"
        "- Pipeline structure (\"what models feed into drug_exposure?\")\n"
        "- Integration guidance (\"how should a new query fit into the pipeline?\")\n\n"
        "Tables are dbt models from EmoryOmopCDW, EmoryPatientIngest, and EmoryPatientIdentityStabilization.\n"
        "Pass bare table names (e.g., \"drug_exposure\") — the tools auto-resolve URNs."
    )

    model_config = {"env_prefix": "", "case_sensitive": False}


settings = Settings()
