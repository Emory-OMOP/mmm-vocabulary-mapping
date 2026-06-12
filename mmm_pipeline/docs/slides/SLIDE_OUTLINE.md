# Workshop slide outline — MindMeetsMachines, OHDSI EU Symposium 2026-04-19

Emory submission: 1-2 slides summarizing the approach. Draft content below
for conversion to Keynote/PowerPoint/Gemini slides.

---

## Slide 1 — The approach

**Title:** *Two-step vocabulary resolution via non-standard embeddings +
community-curated Maps-to*

**Tagline (subtitle):** Leveraging decades of OHDSI manual mapping work
as a retrieval bridge.

### Box 1 — Problem
- 291 source procedure codes from 4 international institutions → OMOP Standard concepts.
- Rules: prefer SNOMED, ignore "unspecified"/"without X", laterality IS meaningful, 1:1 preferred.
- Direct embedding search on standard concepts alone misses ~44% at top-5 on train (R3).

### Box 2 — Pipeline
ASCII diagram (replace with real graphics in deck):

```
source text ─┬─► [ground_clinical_term]                  ─► candidates
             │     (ILIKE → synonym → SapBERT + rerank)       │
             │                                                │
             └─► [standard_via_nonstandard]                   │
                   (SapBERT on 2.6M non-standard concepts     ▼
                    → Maps-to → Standard target)         [RRF fuse]
                                                              │
                                                              ▼
                              Claude (temp=0) with rules in system prompt
                                                              │
                                                              ▼
                              {target_concept_id, predicate, reasoning}
```

### Box 3 — Stack (MCP-native)
- **Model**: SapBERT (cambridgeltl/SapBERT-from-PubMedBERT-fulltext), name-only
  text, 768 dim. Chosen from prior 3×2 factorial eval.
- **Fusion**: Reciprocal Rank Fusion (Cormack et al. SIGIR 2009), k=60.
- **MCP tools**:
  - `standard_via_nonstandard` *(new for this challenge)*: 2.6M non-standard
    concepts → Maps-to → Standard
  - `ground_clinical_term`: existing resolver cascade on 3.25M Standard concepts
- **Rules in system prompt, not in regex**: LLM interprets "ignore 'without X'",
  applies target vocab preference, handles multi-drug regimens.

---

## Slide 2 — Key findings and lessons

**Title:** *What worked, what surprised us, what we'd do next.*

### Retrieval comparison (train set, 71 rows, no LLM picking)

| Method | Recall@1 | Recall@5 |
|---|---:|---:|
| ILIKE name search | 7% | 7% |
| ILIKE + CONCEPT_SYNONYM | 8% | 8% |
| Full cascade (ILIKE → synonym → SapBERT) | 24% | 51% |
| **New 2-step** (non-std embed → Maps-to) | **35%** | **56%** |
| Union (RRF) | pending | **66% ceiling** |

### Key insights

**1. The 2-step resolution matters.**
The new non-standard + Maps-to path (R4) beat the canonical cascade (R3)
on Recall@1 by 11pp. It found 14 correct answers that the cascade missed.
Effective for source strings phrased in source-vocabulary style (ICD10CM,
CPT4, Nebraska Lexicon) where community curation has already bridged the
gap to SNOMED.

**2. R3 and R4 are complementary, not redundant.**
9 rows only R3 finds (especially drug regimens); 14 rows only R4 finds.
Neither alone beats their union. The competition for embedding-based
retrieval is not model choice but retrieval *surface*.

**3. LLM as rule interpreter, not regex.**
We built a regex preprocessor for "(per session)", "WITHOUT COST OF
MATERIALS", etc. — then removed it. Five patterns tuned on 24 observed
failures from 71 examples is textbook overfit. Rules belong in the
system prompt; let the LLM reason in context.

**4. Staging architecture.**
Concept IDs never pass through the LLM — both tools stage results
server-side in a DuckDB session store and return only names + similarity
scores + a result_id. This preserves determinism across conditions and
eliminates an entire class of hallucination pathways (ID fabrication).

### Limitations

- 24/71 train rows have correct target outside top-5 even for R5 union.
  Categories: cross-vocabulary target (CPT4/ICD9Proc over SNOMED when
  preference says otherwise), specificity mismatch, multi-drug regimen
  decomposition. Details in `miss_categories.md`.
- SapBERT name-only outperforms enriched text (synonyms + parents + domain
  concatenated) on our prior eval — contradicting the KEEP framework's
  finding that ontological context helps. Likely due to input-length
  asymmetry between short queries and long enriched concept text.

### What we'd do next

- True ablation study (remove R4, remove R3, full pipeline end-to-end).
- Compare orchestration strategies: Claude Code subagents (with / without
  context inertia from related rows) vs. direct async API calls.
- Source-text normalization via LLM (not regex) as a retrieval preprocessing
  step, measuring whether recall@5 moves toward 85%+.

### Authors

Daniel G. Smith¹²*, Jorge Marquez², Jeselyn Rhodes², Xueqiong (Joan) Zhang¹²,
Benny Budiman².
¹Winship Cancer Institute, Emory University.
²Library & Information Technology Services, Emory University.
*Presenter.

---

## Design notes for the final deck

- Keep each slide to 5-7 lines of body text + 1-2 visuals.
- The pipeline diagram (slide 1 box 2) should be redone as a proper figure
  in the deck — boxes, arrows, and the Maps-to bridge highlighted.
- The retrieval comparison table (slide 2) is the story — numbers should
  be the hero.
- If only 1 slide is allowed, merge Slide 2's table + Slide 1's pipeline
  diagram onto a single page with the 2-step insight as the takeaway.
- Cite SapBERT (Liu et al., NAACL 2021) and RRF (Cormack et al., SIGIR 2009)
  on the slide itself (small font at bottom).
