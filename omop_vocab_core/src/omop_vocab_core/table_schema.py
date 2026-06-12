"""Core logic for OMOP CDM table schema lookups.

This module is pure (no DB access) — it reads from a static JSON schema file
bundled with the package.
"""

import json
from pathlib import Path

_SCHEMA_PATH = Path(__file__).parent / "schemas" / "omop_cdm_schema.json"
with open(_SCHEMA_PATH) as f:
    _SCHEMA = json.load(f)

_TABLES_BY_NAME = {t["name"]: t for t in _SCHEMA["tables"]}

_TABLE_DESCRIPTIONS = {
    "person": "Patient demographics and linking key",
    "observation_period": "Continuous spans of data coverage per patient",
    "condition_occurrence": "Diagnoses and clinical conditions",
    "drug_exposure": "Medications, prescriptions, dispensings",
    "procedure_occurrence": "Clinical procedures performed",
    "measurement": "Lab results, vital signs, quantitative observations",
    "observation": "Clinical observations not covered by other tables",
    "visit_occurrence": "Healthcare encounters (inpatient, outpatient, ER)",
    "visit_detail": "Sub-visit detail within a visit",
    "death": "Patient death records",
    "specimen": "Biological specimen records",
    "device_exposure": "Medical device usage",
    "note": "Clinical notes and documents",
    "note_nlp": "NLP-extracted terms from clinical notes",
    "fact_relationship": "Relationships between clinical facts",
    "location": "Geographic locations",
    "care_site": "Healthcare facilities",
    "concept": "Vocabulary: standardized clinical concepts (7.4M+)",
    "concept_ancestor": "Vocabulary: precomputed concept hierarchy",
    "concept_relationship": "Vocabulary: direct relationships between concepts",
    "drug_strength": "Vocabulary: active ingredient amounts in drug products",
    "cohort_definition": "System: cohort definition metadata",
    "attribute_definition": "System: attribute definition metadata",
    "cdm_source": "System: CDM source and version info",
    "metadata": "System: CDM metadata key-value pairs",
    "cost": "Health economics: cost data linked to clinical events via cost_event_id",
    "payer_plan_period": "Health economics: insurance enrollment spans per patient",
    "drug_era": "Derived: precomputed drug exposure eras (collapsed by ingredient)",
    "condition_era": "Derived: precomputed condition eras (collapsed occurrences)",
    "dose_era": "Derived: precomputed dose eras (constant dose periods)",
}

_TABLE_CATEGORIES = {
    "clinical": [
        "person", "observation_period", "condition_occurrence", "drug_exposure",
        "procedure_occurrence", "measurement", "observation", "visit_occurrence",
        "visit_detail", "death", "specimen", "device_exposure", "note", "note_nlp",
    ],
    "vocabulary": ["concept", "concept_ancestor", "concept_relationship", "drug_strength"],
    "system": ["cohort_definition", "attribute_definition", "cdm_source", "metadata",
               "fact_relationship", "location", "care_site"],
    "health_economics": ["cost", "payer_plan_period"],
    "derived": ["drug_era", "condition_era", "dose_era"],
}

_VOCAB_HINTS = {
    "condition_concept_id": "SNOMED",
    "drug_concept_id": "RxNorm",
    "procedure_concept_id": "SNOMED",
    "measurement_concept_id": "LOINC",
    "observation_concept_id": "SNOMED",
    "device_concept_id": "SNOMED",
    "specimen_concept_id": "SNOMED",
    "visit_concept_id": "Visit",
    "visit_detail_concept_id": "Visit",
    "gender_concept_id": "Gender",
    "race_concept_id": "Race",
    "ethnicity_concept_id": "Ethnicity",
    "unit_concept_id": "UCUM",
    "cause_concept_id": "SNOMED",
    "route_concept_id": "SNOMED",
    "operator_concept_id": "SNOMED",
    "modifier_concept_id": "SNOMED",
    "anatomic_site_concept_id": "SNOMED",
    "disease_status_concept_id": "SNOMED",
    "qualifier_concept_id": "SNOMED",
    "place_of_service_concept_id": "SNOMED",
    "note_type_concept_id": "SNOMED",
    "note_class_concept_id": "SNOMED",
    "encoding_concept_id": "SNOMED",
    "language_concept_id": "SNOMED",
    "admitting_source_concept_id": "SNOMED",
    "discharge_to_concept_id": "SNOMED",
    "death_type_concept_id": "SNOMED",
    "section_concept_id": "SNOMED",
    "note_nlp_concept_id": "SNOMED",
    "cost_type_concept_id": "Type Concept",
    "currency_concept_id": "Currency",
    "revenue_code_concept_id": "Revenue Code",
    "drg_concept_id": "DRG",
    "payer_concept_id": "SOPT",
    "plan_concept_id": "SOPT",
    "sponsor_concept_id": "SOPT",
    "stop_reason_concept_id": "SNOMED",
}

_FK_TARGETS = {
    "person_id": "person.person_id",
    "visit_occurrence_id": "visit_occurrence.visit_occurrence_id",
    "visit_detail_id": "visit_detail.visit_detail_id",
    "provider_id": "provider.provider_id",
    "care_site_id": "care_site.care_site_id",
    "location_id": "location.location_id",
    "preceding_visit_occurrence_id": "visit_occurrence.visit_occurrence_id",
    "preceding_visit_detail_id": "visit_detail.visit_detail_id",
    "visit_detail_parent_id": "visit_detail.visit_detail_id",
    "note_id": "note.note_id",
    "payer_plan_period_id": "payer_plan_period.payer_plan_period_id",
    "drug_era_id": "drug_era.drug_era_id",
    "condition_era_id": "condition_era.condition_era_id",
    "dose_era_id": "dose_era.dose_era_id",
}


def _is_primary_key(table_name: str, col_name: str) -> bool:
    return col_name == f"{table_name}_id"


def _is_restricted(col_name: str) -> bool:
    return col_name.endswith("_source_value") or col_name.endswith("_source_concept_id")


def _column_to_xml(table_name: str, col: dict) -> str:
    name = col["name"]
    attrs = [f'name="{name}"', f'type="{col["type"]}"']

    if col.get("required"):
        attrs.append('required="true"')

    if _is_primary_key(table_name, name):
        attrs.append('key="primary"')
    elif name in _FK_TARGETS:
        attrs.append(f'fk="{_FK_TARGETS[name]}"')

    if name in _VOCAB_HINTS:
        attrs.append(f'vocabulary="{_VOCAB_HINTS[name]}"')

    if _is_restricted(name):
        attrs.append('restricted="true"')

    return f'  <column {" ".join(attrs)}/>'


def _table_to_xml(table_name: str, table: dict) -> str:
    desc = _TABLE_DESCRIPTIONS.get(table_name, "")
    lines = [f'<table name="{table_name}" description="{desc}">']
    for col in table["columns"]:
        lines.append(_column_to_xml(table_name, col))
    lines.append("</table>")
    return "\n".join(lines)


def list_cdm_tables_core(category: str | None = None) -> str:
    """List available OMOP CDM tables grouped by category. Returns XML string."""
    categories = (
        {category: _TABLE_CATEGORIES[category]}
        if category and category in _TABLE_CATEGORIES
        else _TABLE_CATEGORIES
    )

    lines = ["<cdm_tables>"]
    for cat, tables in categories.items():
        lines.append(f'  <category name="{cat}">')
        for tname in tables:
            desc = _TABLE_DESCRIPTIONS.get(tname, "")
            col_count = len(_TABLES_BY_NAME[tname]["columns"]) if tname in _TABLES_BY_NAME else 0
            lines.append(f'    <table name="{tname}" columns="{col_count}" description="{desc}"/>')
        lines.append("  </category>")
    lines.append("</cdm_tables>")
    return "\n".join(lines)


def get_table_schema_core(table_name: str) -> str:
    """Get column schema for a specific OMOP CDM table as XML. Returns XML string or error."""
    table = _TABLES_BY_NAME.get(table_name)
    if not table:
        available = ", ".join(sorted(_TABLES_BY_NAME.keys()))
        return f'<error>Table "{table_name}" not found. Available: {available}</error>'

    return _table_to_xml(table_name, table)
