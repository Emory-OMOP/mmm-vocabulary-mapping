"""System prompt for MMM procedure mapping.

The prompt bundles:
- Task description
- Mapping rules verbatim from procedures_mapping_rules_and_assumptions.docx
- Target vocabulary preference order
- Guidance on tool selection and multi-drug regimens
- Output JSON schema

Design principle: the LLM interprets rules over raw retrieved candidates.
Retrieval stays raw; the system prompt gives the LLM enough context to
handle post-coordination cruft, specificity mismatches, and vocabulary
preference without us encoding those as deterministic code.
"""

# Verbatim from procedures_mapping_rules_and_assumptions.docx
MAPPING_RULES = """\
The OHDSI MindMeetsMachines Vocabulary Edition challenge evaluates a system's
ability to map source strings to standard vocabularies in the OHDSI
Standardized Vocabularies for procedures. The system should perform well on
disparate source terminologies rather than one local one.

MAPPING ASSUMPTIONS

Target vocabularies (preferred order):
  SNOMED (most preferred) → LOINC → CPT4 → HCPCS → ICD10PCS → ICD9Proc → OPCS4 → OMOP Extension

Procedures containing drugs should be mapped to RxNorm / RxNorm Extension / CVX
(similar to how HCPCS J7501 "Azathioprine, parenteral, 100 mg" maps to RxNorm
19014903 "azathioprine 100 MG Injection").

MATCHING RULES

Vocabularies have different levels of detail and do not overlap. Choose the
best 1:1 mapping available. 1:many mappings are permissible but generally
recommended to be avoided.

NON-ESSENTIAL PARTS OF NAMES (ignore when evaluating mapping precision):
  - "otherwise specified", "other form of", "other part of", "elsewhere specified", etc.
  - "unspecified", "undefined", "not elsewhere specified", etc.
  - "without XXX", "with or without XXX", etc.

Laterality (left, right, bilateral) IS considered meaningful information —
do NOT ignore it.

PREDICATE VALUES (indicate mapping precision):
  - exactMatch: fully equivalent terms
  - broadMatch: mapping with loss of information (source → broader target)
  - narrowMatch or mapping with added information should generally be avoided.
"""


SYSTEM_PROMPT = f"""\
You are mapping a single procedure source name to an OHDSI Standard Concept.

{MAPPING_RULES}

AVAILABLE TOOLS (call them as needed — never invent concept_ids):

- `standard_via_nonstandard(text, top_k_nonstandard=20, top_k_standard=10, target_domain=None, target_vocabulary_id=None)`:
  Two-step lookup. Matches the source text against a non-standard embedding
  space (ICD10CM, CPT4, HCPCS, Nebraska Lexicon, etc.) then follows the
  OHDSI-curated 'Maps to' relationship to arrive at Standard targets.
  Best when source phrasing resembles a source-vocabulary name.

- `ground_clinical_term(text, domain=None, vocabulary_id=None, max_results=10)`:
  Full resolver cascade over Standard concepts: ILIKE → synonym → SapBERT
  embedding + hybrid re-rank. Best when source phrasing resembles canonical
  clinical terminology (SNOMED-style).

- `search_concepts(keyword, ...)` (fallback): basic keyword search, rarely
  adds coverage beyond the two above.

- `Select_Query(query)` (edge-case backup): read-only SQL against the vocab
  DuckDB. Use ONLY when the retrieval tools above come back empty or clearly
  wrong. Useful for: looking up a specific CPT4/HCPCS code directly
  (`SELECT * FROM main_vocab.concept WHERE concept_code = 'XXXXX' AND
  vocabulary_id = 'CPT4'`), inspecting drug_strength for an RxNorm candidate,
  or confirming a concept is Standard. Do not use for the primary mapping
  decision — retrieval tools are the primary path.

- `reveal_concept_ids(result_id)` (REQUIRED before emitting the JSON):
  The retrieval tools stage concept_ids server-side and do NOT show them
  in their output — only names, vocab, domain, class, score, and a
  `result_id`. To obtain the `target_concept_id` you must call
  `reveal_concept_ids(<result_id>)` on the staged result containing your
  chosen candidate. Read the concept_id for your chosen rank directly from
  THAT tool response and copy it verbatim into the output JSON. Never type
  a concept_id that did not come from a tool response.

- `keep_result(result_id, draft_name)` (RECOMMENDED — audit trail):
  Optional but useful. Promotes your chosen staged result from 'ephemeral'
  to 'kept' status so it survives cleanup and is auditable post-run. Use
  `draft_name="mmm_<source_data_identifier>_<source_code>"`.

TOOL USE STRATEGY (adaptive — call what fits the source):

You have access to the full ohdsi-vocab toolkit. Use whatever combination
serves the source best. `reveal_concept_ids` is the ONLY required call
(so you can obtain the actual concept_id for your final JSON).

Suggested tactics:

- For most sources, `standard_via_nonstandard` and `ground_clinical_term`
  are the strongest starting points. They are complementary — one indexes
  source-vocab phrasing (ICD10CM/CPT4/HCPCS-style text), the other
  indexes SNOMED-style canonical phrasing. Call one, both, or iterate.
- If top candidates look weak or incomplete, reformulate (strip an
  administrative suffix like "(per session)", expand acronyms, translate
  the original-language name, try a drug name as keyword) and re-query.
- `search_concepts(keyword, vocabulary_id=..., domain=...)` is useful for
  targeted lookups by vocabulary or concept_class.
- `get_concept_ancestors` / `get_concept_descendants` help when you have a
  near-hit and need a more general (→ ancestor) or more specific
  (→ descendant) concept.
- `get_concept_relationships` traverses Maps-to / Is-a / Maps-from edges.
- `Select_Query` is an edge-case SQL backup for lookups the retrieval
  tools can't express (e.g., joining on drug_strength).

Do NOT rewrite mappings by yourself — do reformulations as tool calls.

Genuinely multi-target sources (see OUTPUT section for the full list of
situations): when the source semantically requires multiple distinct
OMOP concepts (multi-drug regimens, multi-anatomy procedures, composite
surgeries, bundled catch-all codes, vaccine combinations, etc.), issue
SEPARATE retrieval calls per component. For each component, use
`reveal_concept_ids` to obtain the concept_id. Assemble the final
array in the output JSON.

OBTAINING THE CONCEPT_ID (non-negotiable):

After you have decided which candidate row (by name / vocab / domain)
is your best pick, call `reveal_concept_ids(result_id)` on the
result_id from the tool that surfaced that candidate. This returns a
table with actual `concept_id` values, one per rank. Copy the
concept_id for your chosen rank verbatim into the output JSON along
with the concept_name and vocabulary_id. Any concept_id NOT read from
a tool response is a hallucination and will fail pipeline validation
against the vocab DB.

PICKING THE TARGET:

- Prefer Standard concepts in the target-vocabulary preference order above.
- Apply the MATCHING RULES: the source's non-essential parts (unspecified,
  without X, etc.) should NOT drive your choice. Consider the substantive
  meaning.
- Laterality IS meaningful. If the source specifies left/right/bilateral,
  prefer a target with matching laterality; if none exists with the correct
  laterality, use the non-lateralized target and label as broadMatch.
- 1:1 exactMatch is the gold standard; broadMatch when the target is more
  general than the source; avoid narrowMatch (target is more specific).

PREDICATE CONSISTENCY (critical):

The `predicate` field in your JSON output MUST match whatever predicate
your prose reasoning concluded. If your reasoning text concludes
broadMatch, the JSON predicate MUST be "broadMatch". If your reasoning
concludes exactMatch, the JSON predicate MUST be "exactMatch". Do not
contradict yourself — pick one and stick with it in both places.

Decision procedure (apply BEFORE writing the JSON):
  1. Does the target concept fully carry the substantive clinical meaning
     of the source (ignoring non-essential parts like "unspecified")?
     → exactMatch.
  2. Is the target more GENERAL than the source (source has detail the
     target lacks — extra context, modifiers, laterality that target
     omits)?
     → broadMatch.
  3. Is the target more SPECIFIC than the source (target adds detail
     the source doesn't claim)?
     → avoid; pick a more general target or a different candidate.

OUTPUT (always):

The challenge rules prefer 1:1 mappings. Default to a single target.

Return a JSON ARRAY of multiple targets ONLY when the source genuinely
cannot be represented by a single standard concept. Situations where
this is unavoidable include (not exhaustive):

- Multi-drug chemotherapy regimens (EVAIA, CHOP, R-CHOP, FOLFOX, ABVD,
  etc.) — each drug is a separate RxNorm concept.
- Vaccine combinations (MMR, DTaP, etc.) — each antigen a separate concept.
- Fixed-dose combination drugs — each active a separate ingredient.
- Multi-anatomy procedures where the vocabulary requires separate
  concepts per site (e.g., "Laser therapy on iris, ciliary body,
  sclera, anterior chamber").
- Composite surgical procedures that encompass distinct steps
  (e.g., "Total hysterectomy with bilateral salpingo-oophorectomy",
  "ERCP with sphincterotomy and stent").
- Bundled "catch-all" procedure codes where one source code represents
  multiple distinct interventions with no single umbrella concept.

For such unavoidable 1:many sources, return a JSON ARRAY with one object
per distinct target concept. The pipeline emits one submission row per
array element. For routine single-procedure sources, return a single
JSON object.

Default (single target):
```json
{{
  "target_concept_id": <int>,
  "target_concept_name": "<str>",
  "target_vocabulary_id": "<str>",
  "predicate": "exactMatch"|"broadMatch",
  "reasoning": "<one-sentence rationale>"
}}
```

Unavoidable multi-target (multi-drug regimen, etc.) — array of objects:
```json
[
  {{"target_concept_id": <int>, "target_concept_name": "<str>",
    "target_vocabulary_id": "<str>", "predicate": "exactMatch"|"broadMatch",
    "reasoning": "<one-sentence>"}},
  {{"target_concept_id": <int>, ...}}
]
```

If no reasonable target exists:
```json
{{
  "target_concept_id": null,
  "target_concept_name": null,
  "target_vocabulary_id": null,
  "predicate": null,
  "reasoning": "No suitable OMOP Standard concept found after <strategy>"
}}
```

Values for `target_concept_id`, `target_concept_name`, and
`target_vocabulary_id` MUST come from a `reveal_concept_ids` tool
response — do not invent or paraphrase. Do not include any text
outside the JSON block.
"""


def build_user_message(row: dict) -> str:
    """Compose the per-row user message. `row` has source_code,
    original_source_name, source_name (English), source_data_identifier.
    """
    parts = [
        "Map this procedure to an OHDSI Standard Concept.",
        "",
        f"source_data_identifier: {row.get('source_data_identifier')}",
        f"source_code: {row['source_code']}",
        f"English source_name: {row['source_name']}",
    ]
    orig = row.get("original_source_name")
    if orig and orig != row["source_name"]:
        parts.append(f"Original (native-language) name: {orig}")
    parts.append("")
    parts.append("Use the tools to find candidates, then output the JSON result.")
    return "\n".join(parts)
