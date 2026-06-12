# Third-party notices — omop_vocab_core

## omop-graph (derivative work — Apache-2.0)

The knowledge-graph layer in this package is a **derivative work** of
[`omop-graph`](https://github.com/AustralianCancerDataNetwork/omop-graph) by
Georgie Kennedy (UNSW / Australian Cancer Data Network), licensed under the
**Apache License, Version 2.0**, at release `0.2.0` (the port derives from the
state shortly after that tag). A copy of the Apache-2.0 license is included in
this directory as [`LICENSE.omop-graph`](LICENSE.omop-graph).

The following modules in `src/omop_vocab_core/` are **ported and redesigned
from** omop-graph and have been **modified from the upstream originals**:

| File | Derived from omop-graph | Notable changes |
|---|---|---|
| `graph_types.py` | graph type/dataclass model (predicate kinds, edges, paths, profiles, explanations, subgraph results) | DuckDB-oriented value types; trimmed to the structures the MMM tools use. |
| `graph_queries.py` | edge/concept/predicate access | Rewritten as raw DuckDB SQL (no SQLAlchemy / omop-alchemy ORM); set-based batched access. |
| `graph_cache.py` | graph context + relationship semantics | Request-scoped dict caches + **runtime** predicate classification from the standard `RELATIONSHIP` table, replacing omop-graph's extension tables and per-node LRU caches. |
| `pathfinding.py` | bidirectional BFS + path scoring | Re-engineered for DuckDB with batch-frontier expansion (one query per BFS level) instead of one `iter_edges()` call per node. |
| `subgraph.py` | multi-hop neighborhood exploration | DuckDB batch traversal with metadata enrichment. |
| `term_grounding.py` | constraint-aware term grounding | `CONCEPT_ANCESTOR` reachability filter over DuckDB search; integrated with the staging layer. |
| `phenotype_simplifier.py` | common-parent coverage / purity simplification | Reimplemented over `CONCEPT_ANCESTOR`. |

**Subsystems intentionally dropped** relative to upstream: the SQLAlchemy /
omop-alchemy ORM, rendering backends (text/HTML/Mermaid), the oaklib interface,
the search-constraint-concept class, and point-in-time validity handling.

This is a **substantial redesign**, not a faithful port — it has documented
behavioral divergences from upstream and is **not** claimed to reproduce
omop-graph's behavior. See `../mmm_pipeline/docs/omop_graph_integration.md`.

## omop-emb (ideas only — no code used)

The semantic-resolution modules (`embedding_search.py`,
`nonstandard_resolver.py`, `concept_set_resolver.py`) were **informed at the
level of ideas** by [`omop-emb`](https://github.com/AustralianCancerDataNetwork/omop-emb)
by Nico Loesch (UNSW), Apache-2.0 — specifically a confidence-tiered resolver cascade
and query-time domain/vocabulary filtering. **None of omop-emb's code is used.**
Our technical path differs: SapBERT embeddings served from DuckDB's VSS/HNSW
index (vs. omop-emb's PostgreSQL/pgvector), plus a source→non-standard→`Maps to`
→standard two-step resolver, hybrid lexical re-ranking, and a concept-id staging
database — components with no upstream analog.
