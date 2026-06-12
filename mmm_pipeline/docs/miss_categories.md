# Miss category analysis — retrieval comparison ceiling

Analysis of the 24 train-set rows where the R5 union (R1 ∪ R3 ∪ R4,
round-robin interleaving) failed to place the correct `target_concept_id`
in top-5. These define the information-theoretic ceiling of any picker
(LLM or otherwise) that operates on the current retrieval output.

Source data: `results/retrieval_ablation.csv`. Row indices refer to the
original train_set.xlsx order.

---

## Category 1 — Post-coordination / administrative cruft

Source strings contain modifiers the rules doc explicitly says to ignore
("without XXX", "unspecified", "otherwise specified") or administrative
annotations that dilute the substantive meaning.

| row | source_name | target | why retrieval failed |
|---|---|---|---|
| 1 | `CT SCAN (>64 SLICES) OF THE VISCEROCRANIUM` | `CT of face` | "(>64 SLICES)" specificity drags embedding away from the broader SNOMED "CT of face" |
| 9 | `CORONAGRAPHY WITHOUT THE COST OF MATERIALS` | `Angiography of coronary artery` | billing suffix pulls embedding toward "without contrast" radiology procedures |
| 31 | `Telemedical individual psychotherapy (per session)` | `Individual psychotherapy` | "Telemedical" and "(per session)" pull toward ICD10PCS / CPT4 variants |
| 32 | `Glaucoma surgery (per side)` | `Operation for glaucoma` | "(per side)" pulls toward specific SNOMED procedure flavors |

**Expected resolution**: in-prompt rule interpretation by the LLM. The
rules list explicitly covers these patterns. An LLM with the rules in
its system prompt should recognize "(per session)", "(per side)",
"WITHOUT THE COST OF MATERIALS", and the slice-count annotation as
non-essential, and pick the substantive match from a broader candidate
list (R5 top-5 with RRF, or by issuing a reformulated tool call).

---

## Category 2 — Specificity mismatch (source / target at different granularity)

Source is more specific than target or vice versa; no exact textual
bridge exists.

| row | source_name | target | mismatch type |
|---|---|---|---|
| 3 | `Search for chlamydia by the direct immunofluorescence method` | `Chlamydia antigen test` | source = method + target; target = assay family |
| 7 | `X-RAY OF BOTH KIDNEYS & URETERS` | `Plain X-ray of kidney, ureter and urinary bladder` | target adds "urinary bladder" (KUB convention) |
| 36 | `Other surgery - orbital cavity (per side)` | `Surgical procedure on orbit` | "orbital cavity" vs "orbit" — anatomical synonym |
| 52 | `Breast-conserving surgery with removal of sentinel lymph node` | `Partial mastectomy with axillary lymphadenectomy` | procedural equivalence that embeddings don't bridge |
| 55 | `Prostate cancer primarily treated with hormonal treatment and then recessed transvesically` | `Suprapubic prostatectomy` | long narrative → specific procedure |
| 56 | (same source) | `Androgen deprivation therapy` | same row, alternative target |
| 61 | `Ultrasound-guided fine-needle aspiration cytology of an axillary lymph node` | `Fine needle aspiration using ultrasound guidance` | target is technique-general; source is body-location-specific |
| 65 | `Ultrasound-guided fine-needle aspiration cytology of a pelvic lymph node` | `Fine needle aspiration using ultrasound guidance` | same pattern |

**Expected resolution**: LLM reasoning + broadMatch predicate. Given the
candidate list, the LLM should recognize when the retrieved concept is
the most substantive match available and label the predicate appropriately.
Retrieval-only cannot bridge these gaps.

---

## Category 3 — Cross-vocabulary target required

Target lives in CPT4 or ICD9Proc but retrieval returns SNOMED variants
of the same procedure. Vocabulary preference ordering (SNOMED > LOINC >
CPT4 > ...) means SNOMED usually wins retrieval; when the gold target
is CPT4 or ICD9Proc, retrieval will miss.

| row | source_name | target (vocab) | retrieval returned |
|---|---|---|---|
| 22 | `Wrist - tenol. in tendovaginitis stenosans wrist muscle` | `Tenolysis... forearm and/or wrist` (CPT4) | SNOMED condition variants |
| 23 | (same source, row duplicated in train set) | same | same |
| 33 | `Laser therapy on iris, ciliary body, sclera, anterior chamber (per session)` | `Operations on iris...` (ICD9Proc) | SNOMED laser iridotomy variants |
| 34 | (same source) | `Photocoagulation of eye` (SNOMED) | same |
| 41 | `Implantation of a cardiac monitor (per session)` | `Insertion, subcutaneous cardiac rhythm monitor...` (CPT4) | SNOMED device + observation variants |
| 46 | `Other surgery - heart and near-heart aorta (per session)` | `Operation on heart` (SNOMED) | ICD9Proc variant |

**Expected resolution**: mostly a judgment call. The vocabulary
preference says SNOMED is preferred when multiple targets exist, so for
rows 33/34/41 the retrieval returning SNOMED is consistent with the
preference — the gold data itself chose a non-preferred vocabulary.
These may be scoreable as broadMatch when the retrieval's SNOMED pick
is semantically close. Rows 22/23 require CPT4-specific signal that
current retrieval doesn't surface.

---

## Category 4 — Abbreviation, shorthand, or term mismatch

| row | source_name | target | issue |
|---|---|---|---|
| 4 | `AEROSOL INHALATION` | `Aerosol therapy` | verb/noun shift that embeddings miss |
| 12 | `BRONCHOINFUSION` | `Bronchoscopic lavage` | obscure term; ICD9Proc-style naming |
| 14 | `NON-STRESS TEST (NST)` | `Cardiotochogram` | obstetrics abbreviation → formal term |

**Expected resolution**: LLM normalization. "NST" → "Non-stress test
(CTG/cardiotochogram)" is a known medical abbreviation the LLM can
expand before or during retrieval.

---

## Category 5 — Procedural nuance / modifier mismatch

| row | source_name | target | issue |
|---|---|---|---|
| 37 | `Radical resection of the temporal bone (per side)` | `Total petrosectomy` | "radical resection of temporal bone" = petrosectomy (not obvious) |
| 38 | `Dilatation of the Eustachian tube (balloon tuboplasty) (per session)` | `Balloon dilation of eustachian tube` | retrieval got "Inflation" instead of "Dilation" |

**Expected resolution**: better candidate list (more top-K depth) +
LLM synonym reasoning. May need top-10 or top-15 from each retriever.

---

## Category 6 — Multi-drug chemotherapy regimen

| rows | source_name | target | drug |
|---|---|---|---|
| 66 | `EVAIA (Day 1-3)` | `dactinomycin` (RxNorm) | E |
| 67 | same | `doxorubicin` | V (or actually doxo) |
| 68 | same | `etoposide` | E |
| 69 | same | `ifosfamide` | I |
| 70 | same | `vincristine` | V |

**Explanation**: EVAIA is the Ewing sarcoma chemotherapy regimen
(etoposide + vincristine + actinomycin + ifosfamide + adriamycin/doxo).
The train set lists each constituent drug as a separate row with the
same source code. This is the only Category-6 case in the 24 misses
but all 5 rows are structurally identical.

**Expected resolution**: LLM decomposition per the system prompt's
multi-drug regimen guidance. The LLM is instructed to recognize known
regimen acronyms (EVAIA, CHOP, R-CHOP, FOLFOX, ABVD) and issue a
separate retrieval call per constituent drug, picking the most
clinically representative one for the submission. For this specific
challenge, the gold data supplies one drug per row as the primary
target — the LLM's decomposition needs to produce that same mapping.

Per-row target mapping:
- Row 66 → dactinomycin (the "A" in EVAIA = actinomycin)
- Row 67 → doxorubicin (the last A/adriamycin)
- Row 68 → etoposide (E)
- Row 69 → ifosfamide (I)
- Row 70 → vincristine (V)

The submission schema allows one target per row, so these 5 rows need
5 separate retrievals even though they share a source_code.

---

## Summary counts

| Category | Rows | Resolvable via | Fraction |
|---|---|---|---|
| 1. Post-coordination cruft | 4 | LLM + rules in prompt | 17% |
| 2. Specificity mismatch | 8 | LLM reasoning + broadMatch | 33% |
| 3. Cross-vocabulary target | 6 | hard; may remain missed | 25% |
| 4. Abbreviation/shorthand | 3 | LLM normalization | 12% |
| 5. Modifier/synonym nuance | 2 | deeper top-K + LLM synonym | 8% |
| 6. Multi-drug regimen | 5 rows × 1 case | LLM decomposition | 21% (5/24) |

Best case if the LLM handles everything correctly: all 24 rescuable except
perhaps a few in Category 3. Realistic floor: 15-20 of 24 rescued, pushing
end-to-end concept_id accuracy above 85% vs. the 66% retrieval-only ceiling.
