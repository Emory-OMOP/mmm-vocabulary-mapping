# SLIDE 1 — DESIGN

## Everything the pptx builder needs (no external context)

**Event**: OHDSI Europe 2026 Symposium · MindMeetsMachines (MMM) Vocabulary Edition workshop
**Date/time**: Sunday April 19 2026, 1-3 pm CET (Rotterdam)
**Task (from challenge rules docx)**: Map procedure source strings from 4 international institutions to **OHDSI Standard concepts for procedures**. Target-vocab preference SNOMED → LOINC → CPT4 → HCPCS → ICD10PCS → ICD9Proc → OPCS4 → OMOP Extension; drug-containing procedures → RxNorm/CVX. Predicate values `exactMatch` / `broadMatch`, avoiding `narrowMatch`.
**Team**: Emory OHDSI Agent — Daniel Smith (Winship Cancer Institute + OIT-DS, Emory University) and collaborators
**Style guide**: mirror the look/feel of `OHDSI_Agent_Presentation__UDP_copy_20260406.pptx` in Downloads (running footer "MMM · Emory OHDSI Agent · Daniel Smith", section-label top-right `SECTION 1 · DESIGN`, icon-plus-text feature boxes, horizontal flow arrows, tight sans-serif typography with one accent color for highlights)
**This deck is exactly 2 slides** — no title card, no agenda. This IS slide 1.

---

## Slide title (top strip, compact — NOT a title card)

**Agentic Procedure-Concept Mapping for MMM** — *explorer → committer over a staged OMOP retrieval stack*

---

## Body — three-panel horizontal flow, left → right

### Panel 1 — RETRIEVAL (staged, no concept_ids to the LLM)

**Two complementary SapBERT indexes over OMOP vocab**

- **R3 `ground_clinical_term`** — 768-dim embeddings over *Standard* concept names (canonical SNOMED phrasing). Recall@5 on train = **51%**.
- **R4 `standard_via_nonstandard`** — 768-dim embeddings over *non-standard* source-vocab names (ICD10CM, CPT4, HCPCS, ...), then follows `Maps to` relationships to reach the Standard target. Recall@5 = **56%**.
- R3 and R4 are complementary — **14 train rows found ONLY by R4, 9 only by R3**. RRF union (Cormack et al. SIGIR 2009, k=60) ceiling = **Recall@5 66%**.
- Tools return concept *names + ranks + result_id*; **concept_ids never appear in the LLM context**.

### Panel 2 — EXPLORER (agent loop, adaptive)

**Full ohdsi-vocab MCP toolkit, LLM picks per row**

- 15+ tools available: `standard_via_nonstandard`, `ground_clinical_term`, `search_concepts`, `get_concept*`, `Select_Query`, ...
- *No forced ordering.* Prompt describes tactics, doesn't prescribe sequence.
- **One mandatory call**: `reveal_concept_ids(result_id)` — returns actual concept_ids for a staged result. LLM reads the ID from the tool response and copies it verbatim → **hallucination-proof**.
- **Multi-target clinical judgment**: for genuinely irreducible sources (multi-drug regimens like EVAIA, CHOP; vaccine combos; bundled catch-all codes; multi-anatomy procedures), LLM returns a JSON *array* → pipeline fans out to N submission rows.
- **Anthropic prompt caching** (`cache_control: ephemeral`) on the system + tools block — ~90% discount on repeat-prefix input tokens; enables concurrency 6 without rate-limit pressure.

### Panel 3 — COMMITTER (validation + recovery)

**Vocab-DB validation + opus-4.7 reviewer fallback**

- Every LLM-emitted concept_id validated against `omop_vocab.duckdb`: **exists** + `standard_concept = 'S'` + not invalidated.
- When the primary agent gets stuck enumerating candidates (haiku, 21-round exploration on CT viscerocranium), pipeline emits null → **opus-4.7 reviewer** reads the *full* assistant transcript from `sessions.db` and commits to a final JSON. No tool access; just reads + emits.
- Submission rows derived strictly from the staging DB, not from LLM digit-typing.

---

## Below the 3-panel flow — DESIGN PRINCIPLES row (4 tight bullets, icon each)

🔒 **Concept_ids flow through DB, not LLM context** — canonical project rule
🎯 **Retrieval raw, reasoning in the prompt** — no regex preprocessing (overfit risk on 71 rows)
🔀 **Adaptive > prescriptive** for capable models — describe tools, don't force sequence
📐 **Input cardinality ≠ clinical cardinality** — LLM decides when multi-target is needed

---

## Right-side sidebar (small, muted) — POST-SUBMISSION RESEARCH

**Isolating "inertia" — a confound in our prior FCA flowsheet-mapping work (3-tier: planner + orchestrator + 10 concurrent reviewers, 76.5% map rate):**

| | inertia | parallelism |
|---|---|---|
| A. CC sequential batch | present | within-batch |
| B. CC shuffled batch | present (random) | within-batch |
| C. CC singleton | absent | per-row |
| **D. API-tight ← today** | **absent** | **per-row async** |
| E. FCA 3-tier replica | present (multi-scale) | 10 concurrent |

---

## VISUAL DIRECTION for the pptx builder

- **No separate title slide** — slide 1 IS the design slide
- Top strip: section label `SECTION 1 · DESIGN` at top-right in a muted accent bar; slide title compact (~1.5cm)
- **Three numbered panels** (1, 2, 3 labeled RETRIEVAL / EXPLORER / COMMITTER) laid horizontally with small arrow separators
- Each panel: heading in accent color, 3-4 bullets with small icons (search-icon for retrieval, robot for explorer, shield-check for committer)
- Design-principles row: 4 equal-width chips at 65% slide height, emoji/icon + bold rule + one-line explanation
- Post-submission sidebar: thin right-column callout with the A/B/C/D/E table, title "Post-submission research", muted fill to de-emphasize
- Footer running text bottom-center: `MMM · Emory OHDSI Agent · Daniel Smith · OHDSI Europe 2026`
- Palette: Emory blue + a single accent color matching the OHDSI Agent deck
