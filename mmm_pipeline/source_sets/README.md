# MMM source sets (not included)

The challenge train/test/gold data and the mapping-rules document come from the official challenge repository and are intentionally **not redistributed** here. To run the pipeline end-to-end, place the following files in this directory:

- `train_set.xlsx` — labeled procedure source codes (sheet `in`), with ground-truth `target_concept_id` / `predicate` columns (used by `score_vs_truth.py`).
- `test_set.xlsx` — unlabeled procedure source codes (sheet `in`) to map and submit.
- `procedures_mapping_rules_and_assumptions.docx` — the task's mapping rules. (The rules text is also embedded verbatim in `../scripts/system_prompt.py`.)

Obtain these from the official OHDSI **Mind Meets Machine — Vocabulary Edition** challenge repository: <https://github.com/ohdsi-studies/MindsMeetMachinesVocab>. These files are git-ignored by default (see the repo `.gitignore`).

Expected columns on the `in` sheet:

```
source_data_identifier, source_code, original_source_name, source_name
```

plus, for the train set, the ground-truth columns:

```
target_concept_id, target_concept_name, alternative_target_concept_id,
alternative_target_concept_name, predicate
```
