# MindMeetsMachines Vocabulary Edition — Procedures Mapping

## Challenge

Map source procedure codes from multiple international institutions to Standard Concepts in the OHDSI Standardized Vocabularies. Workshop at the OHDSI EU Symposium, Sunday April 19 2026, 1pm CET.

See `source_sets/procedures_mapping_rules_and_assumptions.docx` for the rules.

## Task summary

**Input**: source code + native-language name + English translation.

**Output**: source-target pair with predicate (`exactMatch` or `broadMatch`; avoid `narrowMatch`).

**Target vocabularies** (preferred order): SNOMED → LOINC → CPT4 → HCPCS → ICD10PCS → ICD9Proc → OPCS4 → OMOP Extension. Procedures containing drugs → RxNorm / RxNorm Extension / CVX.

**Mapping rules**:

- Choose best 1:1 mapping if available; 1:many permitted but avoided.
- Ignore non-essential modifiers: "unspecified", "otherwise specified", "without X", etc.
- **Laterality is meaningful**.

## Data

- `source_sets/train_set.xlsx` — 71 rows with ground truth (`target_concept_id`, `predicate`, alternates). Use for pipeline validation.
- `source_sets/test_set.xlsx` — 291 rows across 4 source institutions; no target columns. Our pipeline produces these.

## Approach: orchestration experiment

Rather than running a single pipeline, we're framing this as an experiment comparing four orchestration strategies for LLM-driven vocabulary mapping. All four use the same retrieval stack (ILIKE → synonym → embedding → LLM reasoning) and the same candidate reranking. They differ in how work is distributed across agent instances.

| Condition | Description | Inertia | Cost basis |
|---|---|---|---|
| **A. CC-sequential** | Claude Code orchestrator + 10 subagents × ~30 rows, original order | High within-batch | Subscription |
| **B. CC-shuffled** | Same as A but stratified-random row order | Reduced | Subscription |
| **C. CC-singleton** | Claude Code, one subagent per row | None | Subscription |
| **D. API-tight** | Direct `/api/chat` calls, async, tight system prompt | None | API ($$$) |

Each condition runs against the **71-row train set** where ground truth is known. The winner runs against the 291-row test set and produces the submission.

## Metrics

- **Accuracy** — predicate match rate, concept_id exact match, parent-match-within-3-levels
- **Error distribution** — do errors cluster by source institution, domain, or position in batch?
- **Wall-clock** — end-to-end runtime
- **Cost** — subscription tokens consumed vs API dollars spent

## Retrieval stack (shared across conditions)

Order (per `graph_tools_and_semantic_search.md` §3.3.1):

1. **ILIKE** on `concept_name` (exact / prefix match)
2. **CONCEPT_SYNONYM** ILIKE search
3. **SapBERT embedding** search (name-only, cosine via HNSW)
4. **LLM normalization** — agent normalizes lay terms to clinical vocabulary before searching

### Candidate combination

**Primary: Reciprocal Rank Fusion (RRF)** — Cormack, Clarke & Büttcher (SIGIR 2009), "Reciprocal rank fusion outperforms Condorcet and individual rank learning methods." Default `k=60`. Now the standard hybrid-search method in Elasticsearch, OpenSearch, Weaviate, and most modern pgvector RAG stacks. Chosen over the weighted hybrid because the RRF evidence base is industry-scale; Emory's internal eval (§3.3.2 of `graph_tools_and_semantic_search.md`) was a small 30-query pilot.

**Secondary (future comparison):** the Emory production weighted hybrid — Levenshtein 0.4 + Jaccard 0.4 + Brevity 0.2 per paper §3.3.2. Planned as a follow-up experiment, not part of this submission.

After combination, candidates are reranked by vocabulary preference (SNOMED > LOINC > …) as a tiebreaker.

Domain filter: procedures often live in `Procedure` domain, but the train set shows some cross-domain targets (e.g., lab tests in Measurement domain for "Chlamydia antigen test"). We filter by target vocabulary rather than target domain.

## Directory layout

```
publications/mind_meets_machine/
├── README.md                    # this file
├── source_sets/
│   ├── train_set.xlsx           # 71 rows, ground truth
│   ├── test_set.xlsx            # 291 rows, no targets
│   └── procedures_mapping_rules_and_assumptions.docx
├── scripts/
│   ├── mmm_template.py          # ReviewBuilder-style template (Claude Code conditions)
│   ├── mmm_pipeline_api.py      # async HTTP pipeline (API condition)
│   ├── score_vs_truth.py        # shared evaluator
│   └── run_condition.sh         # driver for each condition
├── results/                     # per-condition outputs + scores
└── slides/                      # 1-2 slide deck for the workshop
```

## References

- Challenge announcement: Anna Ostropolets et al., email 2026-04-10
- Mapping rules: `source_sets/procedures_mapping_rules_and_assumptions.docx`
- Retrieval methodology: `docs/publications/graph_tools_and_semantic_search.md`
- Embedding model choice (SapBERT + name-only): §5 of the above
