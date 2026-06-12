# SLIDE 2 — RESULTS

## Everything the pptx builder needs (no external context)

**Event**: OHDSI Europe 2026 Symposium · MindMeetsMachines (MMM) Vocabulary Edition workshop
**Date/time**: Sunday April 19 2026, 1-3 pm CET (Rotterdam)
**Team**: Emory OHDSI Agent — Daniel Smith (Winship Cancer Institute + OIT-DS, Emory University)
**Style guide**: match slide 1's look; section label top-right `SECTION 2 · RESULTS`
**This deck is exactly 2 slides** — this is slide 2 of 2.
**Evaluation**: 72-row train set ground truth (the "training ideal" — same denominator for every model). Position-wise scored (not cartesian-merged); any truth position without a matching model prediction is counted as incorrect for that row. Numbers below are **post-opus-reviewer recovery** — the final pipeline result.

---

## Slide title (top strip, compact)

**MMM Train-Set Results** — *Opus 4.7 commits, Sonnet explores, Haiku runs fast*

---

## Headline stat (large, centered)

# **Opus-4.7 · 47.2% joint_exact** on the 72-row train ground truth
*(concept_id AND predicate both correct — the strictest metric the challenge measures)*
*Opus also has 91.9% predicate accuracy **conditional on concept-correct** — far ahead of Sonnet (76.9%) and Haiku (79.4%).*

---

## Primary table — per-model comparison (denominator = 72 truth rows for every model)

| Model | concept_id_exact | **joint_exact** (primary) | predicate given concept-correct | parent_match_3 | latency / row |
|---|---|---|---|---|---|
| **claude-opus-4-7** | 37/72 · 51.4% | **34/72 · 47.2%** | **34/37 · 91.9%** | 48/72 · 66.7% | ~40 s |
| claude-sonnet-4-6 | **39/72 · 54.2%** | 30/72 · 41.7% | 30/39 · 76.9% | 48/72 · 66.7% | ~30 s |
| claude-haiku-4-5 | 34/72 · 47.2% | 27/72 · 37.5% | 27/34 · 79.4% | 45/72 · 62.5% | ~15 s |

**Why `joint_exact` is the headline, not predicate alone**: predicate accuracy means nothing if the concept is wrong — a row with the wrong concept but an incidentally-matching predicate is still wrong. We report predicate *conditional on concept-correct* for the real predicate skill signal.

**Row-count note**: denominator is held at 72 for every model. Opus fanned 6 multi-target sources (EVAIA → 5 RxNorm drugs, etc.); Sonnet fanned 1; Haiku fanned 0. Truth positions without a matching prediction are counted as incorrect.

---

## Three key observations (one-liners, bullet each)

### ✅ Opus earns its joint_exact lead through predicate skill on correct concepts
When Opus gets the concept right, it gets the predicate right **91.9%** of the time. Sonnet 76.9%, Haiku 79.4%. Opus's 5.5pp joint-exact edge over Sonnet comes from this discipline — not from concept selection (Sonnet actually picks slightly more concepts correctly at 54.2% vs Opus 51.4%).

### ✅ Multi-target fan-out was the biggest structural win for Opus
Previously an EVAIA-style source (5 drugs) could score at most 1/5. With LLM-decided array output, Opus emitted multi-target arrays on 6 irreducible-regimen sources. Haiku emitted 0; Sonnet emitted 1. Those fan-outs are where Opus recovered points Sonnet couldn't.

### ✅ Recovery layer was a safety net, not the accuracy lever
Only 1 row across all three models required the opus-reviewer fallback path — the primary pipeline was robust. Real wins came from architecture (cached prompts, adaptive tools, staged concept_ids), not patching.

---

## Right column — MISS-CATEGORY breakdown (for transparency)

*6 categories, 24 train rows where even R5-union Recall@5 missed the target:*

| Category | N | Our treatment |
|---|---|---|
| Post-coordination cruft (`(per session)`, `(>64 SLICES)`) | 4 | LLM rules in prompt |
| Specificity mismatch (source vs target granularity) | 8 | LLM reasoning — hardest |
| Cross-vocab required (truth = CPT4, retrieval = SNOMED) | 6 | Vocab preference rules |
| Abbreviation / shorthand | 3 | LLM normalization |
| Modifier / synonym nuance | 2 | Deeper top-K |
| Multi-drug regimen (EVAIA, etc.) | 5 | Multi-target array (fixed!) |

---

## Bottom strip — WHAT WE SUBMITTED and WHAT'S NEXT

### Submitted today
**Opus-4.7** · 291-row test set · prompt caching on · concurrency 6 · opus-reviewer recovery for null targets · single submission xlsx (challenge schema)

### Post-submission (near-term)
1. **Postgres staging migration** → remove DuckDB multi-process write lock → restore the clean `(result_id, rank)` contract that further eliminates LLM-as-bus
2. **Full 4+1-condition orchestration study** (A/B/C/D + FCA-replica E) — isolates the inertia confound from our prior unpublished FCA flowsheet-mapping work
3. **Predicate-only isolation study** — predicate accuracy is currently the bright spot (76%); worth understanding why and whether it generalizes

---

## VISUAL DIRECTION for the pptx builder

- **No separate title slide** — slide 2 IS the results slide
- Top strip: section label `SECTION 2 · RESULTS` at top-right; title compact
- **Headline stat**: big centered callout above the table — "50.8%" in display size, accent color, with the explanatory caption in smaller type
- **Main table**: all 3 model rows with opus bolded/highlighted (accent fill on that row); max values per column bolded
- **Key observations**: 3 equal-width cards with green check icon each, ~2 lines of body each
- **Miss-category**: small right-column table with a title "Hardest rows on train" and subtle alternating row fill
- **Bottom strip**: two columns — "Submitted today" (one blob of text) on left, "Post-submission (near-term)" (numbered 3-item list) on right
- Footer: `MMM · Emory OHDSI Agent · Daniel Smith · OHDSI Europe 2026`
- Palette matches slide 1 (Emory blue + single accent); use green for check icons on observations row
