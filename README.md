# MMM Vocabulary Mapping — Emory's 1st-place OHDSI pipeline

This repository shares the vocabulary-mapping pipeline that **Emory University placed 1st overall** with at the OHDSI **Mind Meets Machine (MMM) — Vocabulary Edition** challenge (OHDSI Europe Symposium, Rotterdam, **2026-04-19**). It is released for the OHDSI community as a faithful extract of the winning approach. The challenge itself — task, mapping rules, and data — lives at [`ohdsi-studies/MindsMeetMachinesVocab`](https://github.com/ohdsi-studies/MindsMeetMachinesVocab).

## The result

The MMM Vocabulary Edition was a **procedures-only** task: map ~291 procedure source codes drawn from four institutions (native-language + English names) to OMOP Standard concepts, plus a mapping `predicate`. Emory's submission won 1st place overall and beat the human baseline on all three metrics:

| Metric | Emory | Human baseline |
|---|---|---|
| Overall | **64.0%** | 49.1% |
| Exact match | **74.1%** | 57.0% |
| Broad match | **45.4%** | 32.4% |

The winning configuration was deliberately simple: **one isolated, asynchronous API call per source row** to a FastAPI webapp running a Claude (Opus) MCP tool-loop against the `ohdsi-vocab` retrieval/grounding server, followed by **deterministic re-validation** of every emitted `concept_id` against the OMOP vocabulary. No subagent orchestration.

## Architecture — three layers

1. **Retrieval & grounding** (`omop_vocab_core/` + `mcp_server/`) — the `ohdsi-vocab` MCP server. SapBERT + HNSW embedding search over 7.4M concepts, fused with OHDSI's curated `Maps to` relationships, plus ported OMOP graph-traversal algorithms. `concept_id`s are hidden behind a server-side staging DB and only surfaced on an explicit `reveal_concept_ids` call.
2. **LLM orchestration** (`webapp/backend/`) — a minimal FastAPI backend exposing `POST /api/chat`, which runs the Claude tool-use loop server-side (`max_tool_rounds = 50`) and streams results over SSE. (Only the `/api/chat` path is needed to reproduce; this extract ships no frontend.)
3. **Deterministic safety** (`mmm_pipeline/scripts/mmm_pipeline_api.py` → `validate_against_vocab()`) — every `concept_id` the model emits is re-checked, read-only, against `main_vocab.concept`: it must exist, be Standard, be non-invalid, and its name must match what the model claimed. Anything that fails is dropped. This is what keeps hallucinated IDs out of the submission.

```
                          ┌───────────────────────────────────────────────┐
 test_set.xlsx            │  webapp/backend  (FastAPI, /api/chat)          │
   one row  ───────────►  │    Claude Opus tool-loop  ◄──► ohdsi-vocab MCP │
                          │                               (Layer 1)        │
                          │                          ◄──► omcp MCP         │
                          │                          (read-only OMOP SQL)  │
                          └───────────────┬───────────────────────────────┘
                                          │ JSON {target_concept_id, ...}
                                          ▼
                       validate_against_vocab()  ── read-only ──►  main_vocab.concept
                                          │  (exists / Standard / not-invalid / name match)
                                          ▼
                       submission_formatter.py  ──►  submission_opus.xlsx
```

## Repository layout

```
omop_vocab_core/        Shared OMOP vocab library (DuckDB): search, hierarchy,
                        relationships, SapBERT embedding search, graph traversal,
                        term grounding, concept staging.
mcp_server/             ohdsi-vocab MCP server — registers the Layer-1 tools.
omcp/                   Read-only OMOP SQL MCP server (Select_Query /
                        Get_Information_Schema). Vendored from fastomop/omcp (MIT).
webapp/backend/         FastAPI backend (the /api/chat tool-loop). No frontend.
mmm_pipeline/
  scripts/              The pipeline: mmm_pipeline_api.py (winning driver),
                        system_prompt.py, mmm_recovery.py, submission_formatter.py,
                        score_vs_truth.py, plus embedding-generation helpers.
  source_sets/          (challenge data — not included; from ohdsi-studies/MindsMeetMachinesVocab)
  results/              submission_opus.xlsx — the winning output.
  docs/                 methodology, prompt engineering, slides, graph-tool notes.
LICENSE / NOTICE / ATTRIBUTION.md / PROVENANCE.md
```

This extract is **pinned to the winning commit** (`ee59d10`, the MMM submission). Post-win changes to the source repository are intentionally excluded. The exact source commits of every component in the as-run stack are recorded in [PROVENANCE.md](PROVENANCE.md).

### What was intentionally left out

To keep the repo to the winning vocabulary-mapping path, the following are **excluded**: the `circe-compiler`, `omop-sidecar` (lineage), and `concept-set-constructor` MCP servers; the webapp frontend; the conversation-history database (`sessions.db`); and the large data artifacts (see below). The agent runs on two MCP servers — `ohdsi-vocab` (the primary mapping path: `standard_via_nonstandard` + `ground_clinical_term` + `reveal_concept_ids`) and `omcp` (the read-only `Select_Query` / `Get_Information_Schema` SQL tools the winning run used for a meaningful fraction of rows). The deterministic `validate_against_vocab()` step queries DuckDB directly, independent of omcp.

## Data (not in git)

The pipeline needs the **OMOP vocabulary** and two **SapBERT embedding** indexes. These are large and git-ignored — never committed. This is a vocabulary-mapping task: it queries **only** the OMOP `main_vocab` tables. **No patient/clinical (CDM) data is required.**

| File | ~Size | What it is |
|---|---|---|
| `omop_vocab.duckdb` | ~6 GB | A DuckDB holding the OMOP **vocabulary** in a `main_vocab` schema: concept, concept_ancestor, concept_relationship, concept_synonym, drug_strength, domain, vocabulary, relationship, concept_class. |
| `concept_embeddings.duckdb` | — | SapBERT embeddings of **Standard** concept names + HNSW index (`ground_clinical_term`). |
| `concept_embeddings_nonstandard.duckdb` | ~21 GB | SapBERT embeddings of **non-standard** concept names + HNSW index (`standard_via_nonstandard`). |

By default the code expects all three at the **repo root**; override with `OHDSI_DUCKDB_PATH`, `OHDSI_EMBEDDINGS_DB`, and `OHDSI_NONSTANDARD_EMBEDDINGS_DB`.

Exact data-standard versions (OMOP CDM v5.4 / OMOP Vocabularies Athena v5.0, 2025-02-27) and licenses are in [PROVENANCE.md](PROVENANCE.md).

### Getting the OMOP vocabulary DuckDB

1. Download the OMOP **vocabularies** from OHDSI **Athena** (<https://athena.ohdsi.org>, release v5.0 / 27-FEB-25 — SNOMED, ICD10CM, ICD9CM, RxNorm, RxNorm Extension, LOINC, CPT4, HCPCS, NDC, CVX, …) under the vocabulary providers' license terms. (The vocabulary content is **not** redistributable — it must come from Athena under your own license.)
2. Load the Athena CSVs into a DuckDB `main_vocab` schema (the tab-delimited files map 1:1 to the tables above), e.g. in `duckdb omop_vocab.duckdb`:
   ```sql
   CREATE SCHEMA main_vocab;
   CREATE TABLE main_vocab.concept AS
     FROM read_csv('CONCEPT.csv', delim='\t', header=true, quote='', auto_detect=true);
   -- repeat for CONCEPT_ANCESTOR, CONCEPT_RELATIONSHIP, CONCEPT_SYNONYM,
   -- DRUG_STRENGTH, DOMAIN, VOCABULARY, RELATIONSHIP, CONCEPT_CLASS
   ```
   Point `OHDSI_DUCKDB_PATH` at the result.

### Generating the SapBERT embeddings

The **two** SapBERT indexes — `concept_embeddings.duckdb` (Standard) and `concept_embeddings_nonstandard.duckdb` (non-standard) — are a **derivative of the licensed vocabulary names (SNOMED CT, CPT4, …), so they are never distributed**. You regenerate them locally from the vocabulary DuckDB above (same bring-your-own-licensed-source pattern). Pull the model from its source — Hugging Face `cambridgeltl/SapBERT-from-PubMedBERT-fulltext` at the pinned revision **`090663c3ae57bf35ffe4d0d468a2a88d03051a4d`** (`sentence-transformers` downloads it at runtime; the code defaults to this revision via `OHDSI_EMBED_REVISION`, so encode with the same `revision=` for byte-stable weights). Build **each** index:

1. Read `concept_name` from `main_vocab.concept` with the index's filter — **Standard** `standard_concept='S' AND invalid_reason IS NULL`, **non-standard** `COALESCE(standard_concept,'X')!='S' AND invalid_reason IS NULL` — `ORDER BY concept_id`, and encode each name with SapBERT (`normalize_embeddings=True`, 768-dim, name only). Save a float32 `(N, 768)` `.npy` in that same row order.
2. Build the queryable DuckDB + HNSW index with [`mmm_pipeline/scripts/write_db_fast.py`](mmm_pipeline/scripts/write_db_fast.py):
   ```bash
   # Standard index → concept_embeddings.duckdb
   uv run mmm_pipeline/scripts/write_db_fast.py --npy standard.npy \
       --vocab-db "$OHDSI_DUCKDB_PATH" --filter standard --out concept_embeddings.duckdb
   # Non-standard index → concept_embeddings_nonstandard.duckdb
   uv run mmm_pipeline/scripts/write_db_fast.py --npy nonstandard.npy \
       --vocab-db "$OHDSI_DUCKDB_PATH" --filter nonstandard --out concept_embeddings_nonstandard.duckdb
   ```

[`mmm_pipeline/scripts/generate_embeddings_nonstandard.sh`](mmm_pipeline/scripts/generate_embeddings_nonstandard.sh) wraps step 2 for the non-standard index (point `EMBED_PHASE1` at your step-1 encoder). The `.npy` / `.duckdb` outputs are git-ignored and must never be committed.

## Run the stack

Two ways to bring up the three services (`ohdsi-vocab` :8001, `omcp` :8003, `webapp` :8000). Both assume you've built the vocabulary DuckDB and the two embedding DuckDBs above.

### Option A — Docker (recommended)

Requires Docker + Compose.

```bash
cp .env.example .env
# edit .env:
#   ANTHROPIC_API_KEY   your Claude API key
#   BETA_PASSKEY        a passkey you invent; gates the webapp login (any string)
#   VOCAB_DUCKDB / EMBEDDINGS_DB / NONSTD_EMBEDDINGS_DB   absolute data paths
docker compose up --build
```

This builds and runs all three services, bind-mounting your DuckDBs read-only and wiring the webapp to both MCP servers. The webapp injects the MMM system prompt automatically. Health check: `curl -s localhost:8000/api/health`. Full step-by-step (build → verify → run → tear down) is in [`docs/RUNBOOK.md`](docs/RUNBOOK.md).

### Option B — local (uv, no Docker)

Requires Python ≥ 3.13 and [`uv`](https://docs.astral.sh/uv/).

```bash
export OHDSI_DUCKDB_PATH=/abs/path/to/omop_vocab.duckdb
export OHDSI_EMBEDDINGS_DB=/abs/path/to/concept_embeddings.duckdb
export OHDSI_NONSTANDARD_EMBEDDINGS_DB=/abs/path/to/concept_embeddings_nonstandard.duckdb
export ANTHROPIC_API_KEY=sk-ant-...
export BETA_PASSKEY=choose-a-passkey
bash scripts/start.sh          # starts all three; Ctrl+C stops them
```

In both options the MMM system prompt (task + verbatim mapping rules + tool guidance + output schema) lives in `mmm_pipeline/scripts/system_prompt.py` and is injected into the backend via the `SYSTEM_PROMPT` environment variable.

## Run the pipeline

The pipeline runs on the **host** (Python ≥ 3.13 + [`uv`](https://docs.astral.sh/uv/)): it calls the webapp over HTTP, and the deterministic re-validation + submission formatting open the vocabulary DuckDB directly — so set `OHDSI_DUCKDB_PATH` to the same vocabulary file the stack uses.

```bash
cd mmm_pipeline/scripts

export OHDSI_AGENT_FASTAPI_URL=http://localhost:8000
export OHDSI_AGENT_FASTAPI_PASSKEY=choose-a-passkey   # same as BETA_PASSKEY
export OHDSI_AGENT_FASTAPI_MODEL=claude-opus-4-7
export OHDSI_AGENT_FASTAPI_PROVIDER=claude
export OHDSI_DUCKDB_PATH=/abs/path/to/omop_vocab.duckdb   # for host-side validation/formatting
export OHDSI_VOCAB_SCHEMA=main_vocab

# 1. Map every test row (one isolated async /api/chat call per source row)
uv run mmm_pipeline_api.py ../source_sets/test_set.xlsx --out ../results/api_test.csv --concurrency 10

# 2. (optional) Recover rows where the model explored but never committed a JSON answer.
#    Reads the full assistant text from webapp/data/sessions.db and asks a reviewer model to commit.
uv run mmm_recovery.py --preds ../results/api_test.csv --model claude-opus-4-7

# 3. Format as the challenge submission xlsx (re-validates every target against the vocab)
uv run submission_formatter.py \
    --predictions ../results/api_test.csv \
    --test-set ../source_sets/test_set.xlsx \
    --out ../results/submission.xlsx --strict

# 4. (train set only) Score predictions against ground truth
uv run score_vs_truth.py ../results/api_train.csv --truth ../source_sets/train_set.xlsx
```

`mmm_pipeline/results/submission_opus.xlsx` is the actual winning submission, included for reference. Its **source columns** (`source_data_identifier`, `source_code`, `original_source_name`, `source_name`) are redacted to `___see MMM vocab source repo___` — that challenge data is not redistributed here; obtain it from [`ohdsi-studies/MindsMeetMachinesVocab`](https://github.com/ohdsi-studies/MindsMeetMachinesVocab) and join by row order. Only Emory's predicted target/predicate columns are populated.

## Documentation

- `mmm_pipeline/docs/request_lifecycle.md` — **soup-to-nuts**: how one input row becomes one output row (every deterministic step + the single LLM step), with the full pipeline diagram.
- `mmm_pipeline/docs/technology_stack.md` — every required technology/package, why it exists, and which pipeline stage it serves.
- `mmm_pipeline/docs/methodology.md` — the approach end to end.
- `mmm_pipeline/docs/prompt_engineering.md` — how the system prompt was designed.
- `mmm_pipeline/docs/graph_tools_and_semantic_search.md` — retrieval/grounding internals.
- `mmm_pipeline/docs/omop_graph_integration.md` — what was ported from omop-graph and how it diverges.
- `mmm_pipeline/docs/slides/` — the workshop slides.

## License & attribution

Apache License 2.0 — see [LICENSE](LICENSE). This work builds on **omop-graph** (G. Kennedy, UNSW; Apache-2.0), **SapBERT** (Liu et al., NAACL 2021), the **OHDSI OMOP Standardized Vocabularies**, and the MMM challenge task by its organizers. Full credits and license-compatibility notes are in [ATTRIBUTION.md](ATTRIBUTION.md) and [NOTICE](NOTICE).
