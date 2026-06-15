# Runbook — bring up the stack with Docker

End-to-end steps to run the MMM vocabulary-mapping stack from a clean clone.

## 0. Prerequisites

Build these first — none ship with the repo (all are licensed-derived or large):

- **OMOP vocabulary DuckDB** (`main_vocab` schema) — follow
  [README → Getting the OMOP vocabulary DuckDB](../README.md#getting-the-omop-vocabulary-duckdb)
  (download from Athena, load into a `main_vocab` schema).
- **SapBERT Standard embeddings** (`concept_embeddings.duckdb`) **and**
  **non-standard embeddings** (`concept_embeddings_nonstandard.duckdb`) — follow
  [README → Generating the SapBERT embeddings](../README.md#generating-the-sapbert-embeddings),
  which uses [`mmm_pipeline/scripts/write_db_fast.py`](../mmm_pipeline/scripts/write_db_fast.py)
  (and [`generate_embeddings_nonstandard.sh`](../mmm_pipeline/scripts/generate_embeddings_nonstandard.sh)
  for the non-standard index). Build **both**.
- **Docker + Docker Compose.**
- A **Claude API key**, and the challenge `test_set.xlsx` (from
  [`ohdsi-studies/MindsMeetMachinesVocab`](https://github.com/ohdsi-studies/MindsMeetMachinesVocab))
  in `mmm_pipeline/source_sets/` — only needed for the pipeline run in step 4.

## 1. Configure `.env`

```bash
cp .env.example .env
```

Edit `.env`:

```
ANTHROPIC_API_KEY=sk-ant-...
BETA_PASSKEY=choose-a-passkey
VOCAB_DUCKDB=/abs/path/to/omop_vocab.duckdb
EMBEDDINGS_DB=/abs/path/to/concept_embeddings.duckdb
NONSTD_EMBEDDINGS_DB=/abs/path/to/concept_embeddings_nonstandard.duckdb
```

- `ANTHROPIC_API_KEY` — your Claude API key (the webapp calls the model with it).
- `BETA_PASSKEY` — **a passkey you invent.** The webapp requires it at
  `POST /api/auth/login`, and the pipeline logs in with it to obtain a token; use
  the **same** value for `OHDSI_AGENT_FASTAPI_PASSKEY` in step 4. It's a local
  gate only — any string works.
- the three `*_DUCKDB` paths — absolute paths to the data you built (step 0),
  bind-mounted read-only.

## 2. Build + start

```bash
docker compose build      # first build pulls torch for ohdsi-vocab — large, slow
docker compose up -d
```

## 3. Verify

```bash
docker compose ps
curl -s localhost:8000/api/health | python3 -m json.tool
```

A healthy stack reports `status: ok` with `mcp_servers: 2` and a non-zero
`mcp_tools` (the webapp connected to ohdsi-vocab and omcp). The first
vocabulary query triggers a one-time SapBERT download into the `hf-cache`
volume.

## 4. Run the pipeline (needs `test_set.xlsx`)

The pipeline runs on the **host** (not in a container): it calls the webapp over
HTTP and, for the deterministic re-validation + submission formatting, opens the
vocabulary DuckDB directly. So the host needs Python ≥ 3.13 + [`uv`](https://docs.astral.sh/uv/),
and `OHDSI_DUCKDB_PATH` pointed at the **same** vocabulary DuckDB you mounted in
`.env` (`VOCAB_DUCKDB`).

```bash
cd mmm_pipeline/scripts

export OHDSI_AGENT_FASTAPI_URL=http://localhost:8000
export OHDSI_AGENT_FASTAPI_PASSKEY=choose-a-passkey      # the BETA_PASSKEY from your .env
export OHDSI_AGENT_FASTAPI_MODEL=claude-opus-4-7
export OHDSI_DUCKDB_PATH=/abs/path/to/omop_vocab.duckdb  # same file as VOCAB_DUCKDB in .env
export OHDSI_VOCAB_SCHEMA=main_vocab

# 1. Map every test row (one async /api/chat call per source row)
uv run mmm_pipeline_api.py ../source_sets/test_set.xlsx --out ../results/api_test.csv --concurrency 10

# 2. Format as the challenge submission xlsx (re-validates every target against the vocab)
uv run submission_formatter.py --predictions ../results/api_test.csv \
    --test-set ../source_sets/test_set.xlsx --out ../results/submission.xlsx --strict
```

(Optional `mmm_recovery.py` reads the webapp's `sessions.db`, which under Docker
lives inside the `webapp` container rather than on the host — skip it, or mount a
host `./webapp/data` volume if you want recovery.)

## 5. Tear down

```bash
docker compose down            # keeps the hf-cache volume
docker compose down -v         # also removes the SapBERT cache volume
```

## Troubleshooting

- **`ohdsi-vocab` exits / can't find concepts** — confirm the vocabulary
  schema is `main_vocab` (override with `OHDSI_VOCAB_SCHEMA`), and that
  `VOCAB_DUCKDB` points at a DuckDB with the vocabulary tables.
- **First `/api/chat` is slow** — SapBERT is downloading into `hf-cache`;
  subsequent calls reuse it.
- **`mcp_tools: 0` in health** — a MCP server failed to start; check
  `docker compose logs ohdsi-vocab` / `docker compose logs omcp`.
