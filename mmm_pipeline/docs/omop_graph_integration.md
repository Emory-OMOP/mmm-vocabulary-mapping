# omop-graph Integration: Evaluation and Architectural Decisions

**Date:** 2026-03-28
**Status:** Partially implemented (v0.1.0 graph tools shipped; embedding integration pending)
**Source:** [AustralianCancerDataNetwork/omop-graph](https://github.com/AustralianCancerDataNetwork/OMOP_Graph) (spires branch) and [omop-emb](https://github.com/AustralianCancerDataNetwork/omop-emb.git) (faiss branch)
**Author:** Georgie Kennedy (UNSW), evaluated and ported by Emory OHDSI team

## Context

omop-graph is a Python knowledge graph library for traversing OMOP vocabulary relationships. It provides bidirectional BFS pathfinding, path scoring, subgraph exploration, term grounding, phenotype simplification, and an oaklib interface. The library targets PostgreSQL via SQLAlchemy + omop-alchemy ORM.

We evaluated it for integration into our ohdsi-vocab MCP server (DuckDB-backed, raw SQL, FastMCP) to add graph-level reasoning capabilities that our existing tools lacked.

## What We Ported (v0.1.0)

Three new MCP tools added to ohdsi-vocab, with algorithms adapted for DuckDB and batch edge fetching:

| Tool | Purpose | Output |
|------|---------|--------|
| `find_concept_paths` | Bidirectional BFS between any two concepts | Markdown (ranked paths with step-by-step explanations) |
| `explore_concept_graph` | Multi-hop BFS neighborhood from seed concepts | Markdown (node + edge tables) |
| `ground_clinical_term` | Constraint-aware term grounding with hierarchy reachability | JSON (candidates with path_to_parent evidence) |

**Core library modules** (in `omop_vocab_core`):
- `graph_types.py` — PredicateKind, EdgeView, GraphPath, PathProfile, PathExplanation, SubgraphResult
- `graph_queries.py` — Raw DuckDB SQL for batched edge/concept/predicate fetching
- `graph_cache.py` — GraphContext with in-process dict caches and runtime predicate classification
- `pathfinding.py` — Bidirectional BFS with PathProfile scoring
- `subgraph.py` — BFS traversal with metadata enrichment
- `term_grounding.py` — search_concepts_core + CONCEPT_ANCESTOR reachability filter

### Key adaptation: batch edge fetching

omop-graph issues one `iter_edges()` call per node, relying on SQLAlchemy LRU caches. We batch the entire BFS frontier into a single `WHERE concept_id_1 IN (...)` query per level. This plays to DuckDB's vectorized scan strengths and remains efficient under Postgres (one round-trip per BFS level instead of one per node).

### Predicate classification without extension tables

omop-graph stores relationship semantics in custom `RelationshipClass`/`RelationshipMapping` tables via omop-alchemy. We classify at runtime from the standard RELATIONSHIP table fields (`is_hierarchical`, `defines_ancestry`, `relationship_name`):

- `defines_ancestry = '1'` → ONTOLOGICAL
- name contains "maps to" / "mapped from" / "equivalent" → MAPPING
- name contains "replaced" / "replaces" → VERSIONING
- name starts with "has " → ATTRIBUTE
- everything else → METADATA

Loaded once per GraphContext init (~722 rows).

## What We Skipped and Why

### Skipped permanently

| Component | Reason |
|-----------|--------|
| **omop-alchemy ORM** | We write raw SQL intentionally. ORM adds translation overhead, obscures query patterns during BFS debugging, and couples us to their fork's release cadence. Our SQL is already ANSI-portable across DuckDB and Postgres. |
| **CLI loader** | We use dbt for ETL. Their CLI loads Athena CSVs into Postgres — different pipeline entirely. |
| **SearchConstraintConcept** | Already covered by individual tool parameters (domain, vocabulary_id, standard_only). |

### Deferred — will implement

| Component | Blocker | Value |
|-----------|---------|-------|
| **Phenotype simplifier** (`find_common_parents`, `greedy_parent_cover`) | None — can implement now | Automates concept set curation. Given seed concepts, finds minimum parent set with coverage/pollution/purity metrics. Their `descendants_exhaustive_subsumes()` is broken on spires; we'd rewrite using CONCEPT_ANCESTOR (simpler and faster). |
| **Mermaid renderer** | None — trivial | Optional `format` param on explore/pathfinding tools. ~30 lines. |
| **Embedding resolver** (via omop-emb) | Requires Postgres + pgvector | Fixes ILIKE insufficiency for LOINC, synonym-only terms, semantic matching. See "Embedding integration" below. |
| **oaklib interface** | Low priority | Ecosystem interop with OAK tools. Not agent-facing. Revisit if needed for external tool compatibility. |

## Compound tools identified

Analysis of agent tool-call chains revealed predictable multi-step workflows that should be single tools:

| Proposed tool | Replaces | Round-trips saved |
|---------------|----------|-------------------|
| `resolve_concept_set` | search_concepts → get_descendants → preview_concept_set | 3 → 1 |
| `find_common_ancestor` | Manual BFS via multiple get_ancestors calls (uses phenotype simplifier) | N → 1 |
| `trace_standard_mapping` | search → get_relationships(filter="Maps to") → get_concept | 3 → 1 |

## Embedding integration plan (omop-emb)

### Problem

`search_concepts` uses ILIKE substring matching. Known failures:
- Multi-word LOINC names with different word order
- Synonym-only terms ("heart attack" → "Myocardial infarction")
- Bracketed or punctuated names

### omop-emb architecture

Backend-agnostic embedding layer with pgvector and FAISS backends. Key patterns we'll adopt:

1. **Query embedding reuse** — Before computing a fresh embedding, check if any exact-match concepts exist and reuse their stored embedding as the query vector. Eliminates runtime inference for known terms.
2. **Resolver cascade** — exact → synonym → ILIKE → fulltext → embedding, each with a confidence tier. Stop early on high-confidence match.
3. **Domain/vocab filtering at search time** — applied in the vector query, not as a post-filter.

### Model choice (open)

- `BAAI/bge-small-en-v1.5` (384 dims) — tested, but poor discrimination on domain-specific content (0.85+ cosine for unrelated assertions in our testing).
- `sapbert` — trained on UMLS, purpose-built for biomedical concept matching. Strong candidate.
- `nomic-embed-text-v1.5` (768 dims) — better general discrimination than bge-small.
- omop-emb is model-agnostic; this is a config choice.
