# Technology stack — what, why, and where in the pipeline

Every required technology and package, grouped by the pipeline stage it serves, with why it's there and where it's exercised. Versions are the declared floors (`pyproject.toml` / PEP-723 script headers). See [`request_lifecycle.md`](request_lifecycle.md) for the step-by-step flow these map onto.

## Cross-cutting runtime & tooling

| Tech | Why | Where |
|---|---|---|
| **Python ≥ 3.13** | Language runtime for all services (the standalone pipeline scripts declare ≥ 3.12). | everywhere |
| **uv** | Dependency resolution / virtual envs for each project, and PEP-723 single-file execution (`uv run script.py` with inline deps) for the pipeline drivers. | builds, `mmm_pipeline/scripts/*` |
| **Docker + Compose** | One-command bring-up of the three services with the data bind-mounted; multi-stage images keep `uv` out of the runtime. | `docker-compose.yml`, `docker/` |
| **DuckDB ≥ 1.4.4** | The single analytical engine used end to end — holds the OMOP vocabulary (`main_vocab`), backs vector search via its **VSS/HNSW** extension, and is queried read-only for validation. Embedded, no server. | all stages |

## Stage A — Data preparation (offline, one-time)

| Tech | Why | Where |
|---|---|---|
| **OMOP Standardized Vocabularies (Athena)** | The source data the whole task maps *to*. Loaded into a DuckDB `main_vocab` schema. Licensed — not redistributed. | `omop_vocab.duckdb` |
| **SapBERT** (`cambridgeltl/SapBERT-from-PubMedBERT-fulltext`, pinned revision) | Biomedical entity embeddings of concept names; the semantic-retrieval backbone. Pulled from Hugging Face at the pinned `OHDSI_EMBED_REVISION`. | embeddings build + query |
| **sentence-transformers ≥ 3.0** (→ **torch**) | Loads and runs SapBERT to encode concept names / query text into 768-dim vectors. | `omop_vocab_core/embedding_search.py`, `nonstandard_resolver.py` |
| **DuckDB VSS extension (HNSW)** | Stores the embedding vectors and serves approximate cosine nearest-neighbour search (`array_cosine_similarity`, `USING HNSW … metric='cosine'`). | `write_db_fast.py`, the two `concept_embeddings*.duckdb` |
| **numpy ≥ 1.26 · pyarrow ≥ 14** | Fast, vectorized ingest of the `(N, 768)` embedding matrix into DuckDB (zero-copy Arrow `FixedSizeList`), 10×+ over row-wise inserts. | `mmm_pipeline/scripts/write_db_fast.py` |

## Stage B — Layer 1: retrieval & grounding (`ohdsi-vocab` MCP server, :8001)

| Tech | Why | Where |
|---|---|---|
| **mcp[cli] ≥ 1.26 (FastMCP)** | Hosts the vocabulary/grounding tools as an MCP server over streamable-HTTP (≥ 1.26 required for that transport). | `mcp_server/server.py` |
| **omop-vocab-core** (this repo) | The vocabulary query + graph library: concept search, hierarchy/relationships, the ported OMOP graph traversal, the two SapBERT retrievers, and the concept-id staging DB. | `omop_vocab_core/` |
| **duckdb** | All vocabulary + embedding queries. | `omop_vocab_core/` |
| **sentence-transformers** (`[embeddings]` extra) | Query-time SapBERT encoding for `ground_clinical_term` / `standard_via_nonstandard`. | as Stage A |

## Stage C — SQL tool server (`omcp`, :8003)

| Tech | Why | Where |
|---|---|---|
| **ibis-framework[duckdb] ≥ 10.5** | Backend-portable query layer for the read-only `Select_Query` / `Get_Information_Schema` tools; here bound to DuckDB. | `omcp/` |
| **mcp[cli] ≥ 1.26** | MCP server for the SQL tools (streamable-HTTP). | `omcp/` |
| **langfuse ≥ 3.5** | Optional tracing — **disabled by default** here (`ENABLE_LANGFUSE=false`). | `omcp/` |

## Stage D — Layer 2: orchestration (`webapp` backend, :8000)

| Tech | Why | Where |
|---|---|---|
| **fastapi ≥ 0.115 · uvicorn[standard] ≥ 0.30** | The HTTP server exposing `POST /api/chat` and streaming the agent's events over SSE. | `webapp/backend/main.py` |
| **anthropic ≥ 0.40** | Client for the Claude API — runs the tool-use loop (`ClaudeProvider`) with prompt caching. | `webapp/backend/providers/claude.py` |
| **fastmcp ≥ 2.0** | MCP **client**: connects the backend to the ohdsi-vocab and omcp servers and dispatches tool calls. | `webapp/backend/mcp_client.py` |
| **httpx ≥ 0.27** | Async HTTP transport (Anthropic client + MCP). | backend |
| **pydantic ≥ 2 · pydantic-settings ≥ 2** | Request/response schemas and env-driven config. | `webapp/backend/models.py`, `config.py` |
| **PyJWT ≥ 2.8** | Issues/validates the JWT minted from `BETA_PASSKEY` at `/api/auth/login`. | `webapp/backend/auth.py` |
| **langfuse ≥ 3.0** | Optional observability — **off by default** (`LANGFUSE_ENABLED=false`). | `webapp/backend/observability.py` |

## Stage E — Pipeline driver & deterministic validation (`mmm_pipeline/scripts/`)

| Tech | Why | Where |
|---|---|---|
| **httpx ≥ 0.27** | Async client: logs in, fires one `/api/chat` per row, parses the SSE stream. | `mmm_pipeline_api.py` |
| **pandas ≥ 2.0 · openpyxl ≥ 3.1** | Read the input `.xlsx`, de-duplicate rows, write the CSV / submission `.xlsx`. | `mmm_pipeline_api.py`, `submission_formatter.py`, `score_vs_truth.py` |
| **duckdb** | The **boundary validation** gate — read-only checks of every emitted `concept_id` against `main_vocab.concept`; also the parent-distance scoring. | `validate_against_vocab`, `score_vs_truth.py` |
| **anthropic ≥ 0.40** | The optional recovery reviewer (no tools, single commit). | `mmm_recovery.py` |
| **aiofiles** | Async file IO alongside the concurrent request driver. | `mmm_pipeline_api.py` |

## The model

| Tech | Why |
|---|---|
| **Claude `claude-opus-4-7`** (Anthropic API) | The clinical-reasoning step: picks retrievers, reformulates, and selects the Standard target. The winning submission model; also the recovery reviewer. The default `claude-opus-4-7` is an alias mapped in the webapp config. |

## Methods (not packages, but load-bearing)

- **SapBERT + HNSW cosine** — semantic concept retrieval over name embeddings.
- **RRF (Reciprocal Rank Fusion, k=60)** — fuses the two retrievers' ranked lists.
- **Bidirectional BFS graph traversal** — pathfinding/neighbourhood over `CONCEPT_RELATIONSHIP` (ported & redesigned from omop-graph; see `omop_graph_integration.md`).
- **Concept-id staging** — retrievers return names/score/rank/`result_id` only; ids are revealed on an explicit call so the model can't fabricate them.
- **Balanced-brace JSON extraction** — robustly pulls the final answer JSON from free-form model text.
- **Deterministic re-validation** — exists / Standard / not-invalid / name-match against the vocabulary; the hallucination backstop.

> Out of scope (not required for this pipeline): the `circe-compiler`, `omop-sidecar`, and `concept-set-constructor` MCP servers; any patient/CDM data; and Langfuse (optional, off by default).
