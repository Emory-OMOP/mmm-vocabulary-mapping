# Attribution

This repository shares Emory University's 1st-place vocabulary-mapping pipeline from the OHDSI **Mind Meets Machine (MMM) Vocabulary Edition** challenge (OHDSI Europe Symposium, Rotterdam, 2026-04-19). It builds on work by several other projects and communities. This file records what we used, how, and under what terms.

The repository as a whole is released under the **Apache License, Version 2.0** (see [LICENSE](LICENSE)).

## omop-graph (graph traversal & term grounding)

- **Project:** `omop-graph` — "Explainable, OMOP-native knowledge graph traversal and pathfinding"
- **Author:** Georgie Kennedy (UNSW / Australian Cancer Data Network)
- **Upstream:** <https://github.com/AustralianCancerDataNetwork/omop-graph> — cited at **release `0.2.0`** (2026-01-12). The graph layer derives from the state shortly after that tag (commit `3a0b1aa`, 2026-02-09). See [PROVENANCE.md](PROVENANCE.md).
- **License:** Apache License 2.0 (declared in the project's `pyproject.toml`: `license = { text = "Apache-2.0" }`, classifier `License :: OSI Approved :: Apache Software License`).

**This is a derivative work, not an independent reimplementation.** The knowledge-graph layer in `omop_vocab_core/` **descends from** omop-graph: we **ported and redesigned** its graph-reasoning algorithms — bidirectional-BFS pathfinding, path-quality ranking, multi-hop subgraph exploration, runtime predicate classification, and phenotype-simplification (common-parent coverage/purity) — re-engineering them for a DuckDB backend. In doing so we changed the code substantially: we removed the SQLAlchemy / omop-alchemy ORM in favor of raw DuckDB SQL, replaced per-node LRU caching with request-scoped batch-frontier fetching, classify relationships at runtime from the standard `RELATIONSHIP` table instead of extension tables, and dropped the rendering, oaklib-interface, resolver-class, and point-in-time-validity subsystems. These are **modifications to a derivative of omop-graph**, and we credit Georgie Kennedy / UNSW accordingly.

Because the graph layer is a derivative of omop-graph's Apache-2.0 code (both projects are Apache-2.0, so there is no license conflict), this distribution:
- **carries omop-graph's Apache-2.0 license** alongside the derived modules at [`omop_vocab_core/LICENSE.omop-graph`](omop_vocab_core/LICENSE.omop-graph);
- **states the changes** and enumerates the derived files in [`omop_vocab_core/THIRD_PARTY_NOTICES.md`](omop_vocab_core/THIRD_PARTY_NOTICES.md); and
- retains the "modified from upstream" statement here and in [`NOTICE`](NOTICE).

The graph layer is **substantially redesigned** from omop-graph, with documented divergences (see `mmm_pipeline/docs/omop_graph_integration.md`); it is **not** claimed to reproduce upstream behavior.

**Companion library `omop-emb` (ideas only).** [`omop-emb`](https://github.com/AustralianCancerDataNetwork/omop-emb) (Nico Loesch, UNSW; Apache-2.0) **informed our design at the level of ideas only** (a confidence-tiered resolver cascade; query-time domain/vocabulary filtering). We use **none of its code** and took a different technical path: SapBERT embeddings served from DuckDB's VSS extension with an HNSW index, rather than omop-emb's PostgreSQL/pgvector stack. Our semantic layer additionally introduces components with no upstream analog — a source→non-standard-embedding→`Maps to`→standard two-step resolver, hybrid lexical re-ranking, and a concept-id staging database that keeps concept identifiers out of the language-model context.

## FastOMOP / omcp (read-only OMOP SQL server — vendored in `omcp/`)

- **Project:** `omcp` — the FastOMOP OMOP SQL-execution and validation MCP server.
- **Upstream:** <https://github.com/fastomop/omcp> (FastOMOP organization; King's College London / UCL / NHS).
- **License:** MIT — the upstream MIT license text travels with the vendored copy at [`omcp/LICENSE`](omcp/LICENSE).
- **How it is used here.** `omcp/` provides the read-only `Select_Query` and `Get_Information_Schema` SQL tools. The winning run called `Select_Query` on a meaningful fraction of rows, so omcp is part of the reproducible stack and is included.
- **Derived from `fastomop/omcp@4922d41`, with modifications:** removed `Lookup_Drug` and `Lookup_Condition` (leaving the two read-only SQL tools); DuckDB connect-per-query; `mcp >= 1.26` with streamable-HTTP transport; OMOP cohort-table access with PII-column protection. See [PROVENANCE.md](PROVENANCE.md).

## SapBERT (semantic concept embeddings)

- **Model:** `cambridgeltl/SapBERT-from-PubMedBERT-fulltext` (Hugging Face), pinned at revision **`090663c3ae57bf35ffe4d0d468a2a88d03051a4d`** (last modified 2023-06-14).
- **Paper:** Fangyu Liu, Ehsan Shareghi, Zaiqiao Meng, Marco Basaldella, Nigel Collier. *Self-Alignment Pretraining for Biomedical Entity Representations.* NAACL 2021. <https://aclanthology.org/2021.naacl-main.334/>
- **License:** **Apache-2.0** (per the Hugging Face model card). The model is **not** redistributed here; `sentence-transformers` downloads it at runtime from Hugging Face.
- **How it is used here.** SapBERT produces name-only embeddings of OMOP concept names. Those embeddings are indexed in DuckDB (HNSW) and queried for semantic concept retrieval (`embedding_search.py`, `nonstandard_resolver.py`, exposed via the `ground_clinical_term` and `standard_via_nonstandard` tools).
- **Reproducibility:** the exact revision above is the **default in code** (`OHDSI_EMBED_REVISION`), so `sentence-transformers` resolves the same weights every time instead of floating to the model repo's latest commit. The embedding DuckDBs are regenerated locally (never distributed — they derive from licensed vocabulary names).

## OHDSI OMOP Standardized Vocabularies

- **Source:** OHDSI — distributed via Athena, <https://athena.ohdsi.org>
- **How it is used here.** The `concept`, `concept_ancestor`, `concept_relationship`, `drug_strength`, and related tables are the data this software queries (schema `main_vocab`). They are governed by the respective vocabulary providers' license terms (e.g., SNOMED CT affiliate licensing, where applicable). They are **not** redistributed in this repository — obtain them from Athena. See the README "Data" section.

## MMM challenge (task, rules, and source sets)

- **Organizers:** Anna Ostropolets, Martijn Schuemie, Tom Seinen, Matthijs Otten-Wagenaar (OHDSI / Erasmus MC).
- **Event:** "Mind Meets Machine — Vocabulary Edition," OHDSI Europe Symposium, Rotterdam, 2026-04-19.
- **Challenge repository:** <https://github.com/ohdsi-studies/MindsMeetMachinesVocab> — the official source for the task, mapping rules, and train/test/gold data.
- **What we use.** The procedure-mapping task definition and the mapping rules. The verbatim mapping-rules text is embedded in `mmm_pipeline/scripts/system_prompt.py` because it is load-bearing for reproduction. The **train/test/gold source sets are NOT redistributed here** — obtain them from the challenge repository above (see `mmm_pipeline/source_sets/README.md`).
