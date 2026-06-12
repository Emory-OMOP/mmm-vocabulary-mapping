# Provenance — the as-run stack

This repository is a faithful extract of the stack that produced Emory's 1st-place result at the OHDSI **Mind Meets Machine (MMM) — Vocabulary Edition** challenge (OHDSI Europe Symposium, Rotterdam). The challenge *ran* on 2026-04-19 from an uncommitted working tree; the code and results were committed retroactively. For reproducibility and citation, the exact source of each component is recorded below.

Upstream components are cited at their **canonical homes and releases** — not at the Emory or other forks that happened to be checked out locally during the run.

| Component | Canonical upstream | Release / commit | Date | Role |
|---|---|---|---|---|
| ohdsi-vocab MCP, webapp backend, `omop_vocab_core` (graph + grounding), MMM pipeline scripts, winning `submission_opus.xlsx` | `EmoryDataSolutions/emory_ohdsi_agent` | **`ee59d10`** (PR #13) | 2026-04-27 | The code in *this* repository. First/only commit containing the two load-bearing retrieval tools the run used (`standard_via_nonstandard.py`, `nonstandard_resolver.py`) plus the pipeline scripts and the submission. The earlier `44a12f6` (#12) lacks those tools. |
| omop-graph (graph-traversal / term-grounding layer — **derivative work**, port+redesign in `omop_vocab_core/`) | **`github.com/AustralianCancerDataNetwork/omop-graph`** (Georgie Kennedy, UNSW) | **release `0.2.0`** (2026-01-12); derived from the state shortly after that tag (commit `3a0b1aa`, 2026-02-09) | 2026-01-12 / 2026-02-09 | The graph modules in `omop_vocab_core/` are a **derivative work** of omop-graph — ported and substantially redesigned for DuckDB, **modified from upstream**. Apache-2.0. Per Apache-2.0, this repo carries omop-graph's license at `omop_vocab_core/LICENSE.omop-graph` and states the changes in `omop_vocab_core/THIRD_PARTY_NOTICES.md`. NOT claimed to reproduce upstream behavior. See `ATTRIBUTION.md` + `mmm_pipeline/docs/omop_graph_integration.md`. |
| omcp (read-only OMOP SQL MCP — *vendored in `omcp/`*) | **`github.com/fastomop/omcp@4922d41`** (FastOMOP; King's College London / UCL / NHS) | derived from `4922d41` | — | The clinical-SQL server. The winning run called `Select_Query` (an omcp tool) on 28 of the 291 rows, so it is part of the reproducible stack. MIT-licensed; the MIT notice travels with the vendored copy (`omcp/LICENSE`). See modifications note below. |

**`omcp/` modifications.** The vendored `omcp/` is derived from `fastomop/omcp@4922d41` (MIT) with these changes: removed the `Lookup_Drug` and `Lookup_Condition` tools (leaving the two read-only SQL tools `Select_Query` and `Get_Information_Schema`); DuckDB connect-per-query (one connection per query, for safe concurrent reads); `mcp >= 1.26` with streamable-HTTP transport; and OMOP cohort-table access with PII-column protection. These are described as prose modifications; the MIT license text is included at `omcp/LICENSE`.

**Data dependency** (not redistributed in this repo — see the README "Data" section). MMM is a vocabulary-mapping task; its **only** data dependency is the OMOP vocabulary. No patient/clinical (CDM) data is required.

| Artifact | Version / source | License / terms |
|---|---|---|
| OMOP Standardized Vocabularies | **Athena v5.0**, vocabulary release **2025-02-27**, via <https://athena.ohdsi.org> (loaded into a DuckDB `main_vocab` schema) | Per each vocabulary provider's terms (e.g. SNOMED CT affiliate licensing where applicable) |
| OMOP Common Data Model | **CDM v5.4** (table structure the vocabulary conforms to) | CC-BY-4.0 (OHDSI) |

The vocabulary content embeds Athena-licensed data and cannot be redistributed; each user downloads it from Athena and loads it locally.

**Embedding model:** SapBERT `cambridgeltl/SapBERT-from-PubMedBERT-fulltext` @ Hugging Face revision **`090663c3ae57bf35ffe4d0d468a2a88d03051a4d`** (last modified 2023-06-14; **Apache-2.0**) — cite Liu et al., NAACL 2021. This is the exact revision the winning run used; the code defaults to it (`OHDSI_EMBED_REVISION`). The SapBERT embedding DuckDBs are a **separate**, **never-distributed** artifact (derivative of licensed vocabulary names) — each user regenerates them locally. See `ATTRIBUTION.md` and the README "Data" section.

**Not part of the winning run (reference only):** `omop-emb` (`github.com/AustralianCancerDataNetwork/omop-emb`, Nico Loesch, UNSW; Apache-2.0; release `v0.1.0`, 2026-03-22) is discussed in the design notes as a *planned* embedding integration. The winning run used Emory's own SapBERT + DuckDB/HNSW embedding pipeline (`embedding_search.py`, `nonstandard_resolver.py`), **not** omop-emb.

## What is and isn't in this repo

- **Vendored / extracted here:** `emory_ohdsi_agent` content at `ee59d10`, pruned to the vocabulary-mapping path (Layer 1 retrieval/grounding, the `/api/chat` backend, and the deterministic-validation pipeline scripts); plus the `omcp/` read-only SQL server (derived from `fastomop/omcp@4922d41`, MIT).
- **Re-implemented, not copied:** the omop-graph algorithms (a DuckDB re-implementation — see the integration note).
- **Referenced but not included:** `omop-emb`; the OMOP vocabulary data; the SapBERT model; the challenge task/rules/source sets (official repo: <https://github.com/ohdsi-studies/MindsMeetMachinesVocab>).

> Note: the historical design note `mmm_pipeline/docs/omop_graph_integration.md` (dated 2026-03-28) references omop-graph via the `AustralianCancerDataNetwork/OMOP_Graph` repo on the `spires` branch — the working reference at the time. The canonical upstream cited throughout this repository is `AustralianCancerDataNetwork/omop-graph` (lowercase, default branch), release `0.2.0`.
