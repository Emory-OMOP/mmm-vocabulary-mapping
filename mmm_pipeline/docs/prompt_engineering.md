# Prompt Engineering Journal — MMM Vocabulary Edition

Canonical prompt lives in `scripts/system_prompt.py`. This doc captures the
iterative evolution of the prompt + the empirical results from the 71-row
training set that drove each change.

## v0 — Initial prompt (copied from docx verbatim)

The first iteration faithfully encoded the rules from
`source_sets/procedures_mapping_rules_and_assumptions.docx`:

- Task description + the sentence "for procedures" (confirms domain)
- Target-vocab preference: SNOMED → LOINC → CPT4 → HCPCS → ICD10PCS → ICD9Proc → OPCS4 → OMOP Extension
- Matching rules: ignore `unspecified`/`without XXX`; laterality IS meaningful
- Predicate definitions: `exactMatch` / `broadMatch`; avoid `narrowMatch`

**Tool use strategy**: "Call BOTH `standard_via_nonstandard` and `ground_clinical_term`" — forced every row to issue at least two retrieval calls.

**Output contract**: single JSON object with `target_concept_id`,
`target_concept_name`, `target_vocabulary_id`, `predicate`, `reasoning`.

### Problem discovered — concept_id hallucination

First smoke runs (3 rows) produced JSON output with plausible-looking but
WRONG concept_ids:

| Model | source | LLM emitted | Actual concept in vocab | Truth |
|---|---|---|---|---|
| Sonnet | INDIVIDUAL PSYCHOTHERAPY | 4148235 | "Creation of arterial bypass with synthetic graft" | 4088889 |
| Haiku | INDIVIDUAL PSYCHOTHERAPY | 4172703 | "=" (SNOMED qualifier value) | 4088889 |

Root cause: retrieval tools intentionally **stage concept_ids server-side
and do not expose them in markdown output** (only names + rank + result_id).
The prompt asked the LLM for `target_concept_id` with no reliable source,
so both models invented plausible 7-digit numbers.

## v1 — Staging-DB-as-bus (abandoned)

Attempted fix: change output contract so the LLM emits `(result_id, rank)`
instead of `concept_id`; pipeline reads the staging DB and resolves.

**Train run at concurrency 10**: 52/71 sonnet errors, 54/71 haiku errors.

Root cause: DuckDB staging DB does NOT allow concurrent RO reader from a
second process while the MCP server holds a RW connection. Lock-conflict
errors on the first source per run.

Deferred: migrate staging backend to Postgres post-deadline and retry the
clean (result_id, rank) contract.

## v2 — `reveal_concept_ids` with vocab-DB validation (current)

Reverted to concept_id-emitting output, but added:

1. **Mandatory tool call** `reveal_concept_ids(result_id)` before emitting
   the JSON. This tool (already in ohdsi-vocab) returns the actual
   concept_ids for a staged result. The LLM reads the ID from the
   tool response and copies it verbatim — no hallucination possible if
   the LLM copies faithfully.

2. **Pipeline-side vocab DB validation** (`validate_against_vocab` in
   `mmm_pipeline_api.py`). Every LLM-emitted concept_id is checked against
   `omop_vocab.duckdb` for: exists, `standard_concept='S'`, not
   invalidated, AND the LLM's claimed name matches the vocab's
   authoritative name. Validation failure nulls the prediction and
   flags the row.

Result: psychotherapy row now resolves to correct concept_id **4088889**
across sonnet and haiku.

### Predicate-consistency rule

Observed in one row: sonnet's prose reasoning concluded "This is a
broadMatch" but its JSON predicate field said "exactMatch". Added
explicit decision procedure + "do not contradict yourself" instruction.
Train run at concurrency=3 showed predicate_match at 37% (sonnet),
suggesting predicate selection is the dominant error source (larger than
concept_id selection at 31%).

## v3 — Adaptive tool use (current)

Earlier prompt *required* both `standard_via_nonstandard` and
`ground_clinical_term` as step 1. This wasted tokens on easy rows and
confused the model when the two tools disagreed.

**Relaxed to adaptive**: the prompt now enumerates the full useful ohdsi-vocab
toolkit — `search_concepts`, `get_concept`, `get_concept_ancestors`,
`get_concept_descendants`, `get_concept_relationships`, `Select_Query`
(omcp), `reveal_concept_ids`, `keep_result` — and lets the LLM call
whatever fits. Only `reveal_concept_ids` is required (for the concept_id
obtain step). Smoke runs confirm the LLM correctly uses additional
tools on harder rows (e.g., `search_concepts` + `get_concept` for
CT-viscerocranium, `Select_Query` for OPS catch-alls).

## v4 — Multi-target output (current)

Observed in train: 7 sources have >1 truth concept (EVAIA → 5 drugs;
BE520 → 2 anatomy sites; DZ099 → catch-all; etc.). Test set has ZERO
duplicates across 291 rows, so the multi-target signal cannot come from
input duplication.

**Solution**: let the LLM decide. Output schema now accepts either:
- **Single JSON object** (default, 1:1 mapping) — pipeline emits 1
  submission row
- **JSON array of objects** (unavoidable 1:many) — pipeline fans out
  to N submission rows

Decision criteria spelled out in prompt: multi-drug regimens, vaccine
combinations, fixed-dose combo drugs, multi-anatomy procedures,
composite surgical procedures, bundled catch-all codes.

## v5 — Infrastructure: prompt caching

Not a prompt-content change but a provider-side optimization. Anthropic's
`cache_control: {type: ephemeral}` on the system prompt + last tool
block reduces repeat-request input cost by ~90%. Enables higher
concurrency (6+) without hitting the 450k-tok/min sonnet rate limit.

## Empirical milestones

| Version | Sonnet concept_id_exact | Sonnet predicate_match | Notes |
|---|---|---|---|
| v0 | N/A (hallucinations) | N/A | Smoke test revealed bogus concept_ids |
| v1 | Aborted — staging DB lock conflicts | | 52/71 errors at concurrency 10 |
| v2 (+ concurrency 3, str-key merge fix, position-wise align) | 14/71 (19.7%) | 21/71 (29.6%) | First trustworthy scores |
| v3+v4+v5 | (rerun in progress) | | With adaptive tools + multi-target + caching |

## Principles learned

1. **Never ask the LLM for opaque identifiers** unless it just read them
   from a tool response. Hallucination risk scales with digit count and
   recency.
2. **Validate LLM output at system boundaries**, not inside the agent.
   Vocab DB check is fast (ms), cheap, and catches every class of
   concept_id error we've seen.
3. **Adaptive > prescriptive** for capable models. Requiring specific
   tools wastes tokens and constrains reasoning; describing tools as
   available + suggesting tactics works better.
4. **Input cardinality ≠ clinical cardinality.** Don't encode output
   structure based on input row duplication — let clinical judgment
   drive it.
5. **Predicate distinction** (line 14 of docx: "distinguish exact
   mapping from that with loss of information") is an independent
   accuracy axis from concept selection. Explicit decision procedure
   helps.
