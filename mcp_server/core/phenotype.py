"""Core logic for OHDSI PhenotypeLibrary search and retrieval."""

import csv
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data" / "phenotype_library"
_COHORTS_CSV = _DATA_DIR / "Cohorts.csv"
_COHORTS_DIR = _DATA_DIR / "cohorts"

_SEARCH_COLUMNS = [
    "cohortId", "cohortName", "status", "logicDescription", "hashTag",
    "numberOfConceptSets", "numberOfInclusionRules",
    "domainConditionOccurrence", "domainDrugExposure",
    "domainProcedureOccurrence", "domainMeasurement", "domainObservation",
    "domainVisitOccurrence", "domainDeviceExposure", "domainDeath",
]

_DOMAIN_COLUMNS = {
    "condition": "domainConditionOccurrence",
    "drug": "domainDrugExposure",
    "procedure": "domainProcedureOccurrence",
    "measurement": "domainMeasurement",
    "observation": "domainObservation",
    "visit": "domainVisitOccurrence",
    "device": "domainDeviceExposure",
    "death": "domainDeath",
}

_cohort_index: list[dict] | None = None


def _load_index() -> list[dict]:
    global _cohort_index
    if _cohort_index is not None:
        return _cohort_index

    if not _COHORTS_CSV.exists():
        logger.warning(
            "PhenotypeLibrary data not found at %s. "
            "Run scripts/download_phenotype_library.sh first.",
            _DATA_DIR,
        )
        _cohort_index = []
        return _cohort_index

    rows = []
    with open(_COHORTS_CSV, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [
            h.strip().strip('"').strip() for h in reader.fieldnames
        ]
        for row in reader:
            entry = {}
            for col in _SEARCH_COLUMNS:
                val = row.get(col, "")
                entry[col] = val
            try:
                entry["cohortId"] = int(entry["cohortId"])
            except (ValueError, TypeError):
                continue
            rows.append(entry)

    _cohort_index = rows
    logger.info("Loaded %d phenotype entries from Cohorts.csv", len(rows))
    return _cohort_index


def _match_score(entry: dict, keyword: str) -> int:
    kw = keyword.lower()
    score = 0

    name = (entry.get("cohortName") or "").lower()
    desc = (entry.get("logicDescription") or "").lower()
    tags = (entry.get("hashTag") or "").lower()

    if kw in name:
        score += 10
        if f" {kw}" in name or name.startswith(kw):
            score += 5
    if kw in desc:
        score += 5
    if kw in tags:
        score += 3

    return score


def format_domains(entry: dict) -> str:
    """Format active domain flags into a compact string."""
    domains = []
    for short_name, col in _DOMAIN_COLUMNS.items():
        if entry.get(col) in ("1", "TRUE", "true", True):
            domains.append(short_name)
    return ", ".join(domains) if domains else "none"


def search_phenotypes_core(
    keyword: str,
    domain: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> tuple[list[dict], int] | str:
    """Search PhenotypeLibrary for curated cohort definitions.

    Returns (results, total_matches) on success, or an error string.
    Each result dict has keys from _SEARCH_COLUMNS.
    """
    limit = min(max(1, limit), 30)
    index = _load_index()

    if not index:
        return "Phenotype Library data not available. Run scripts/download_phenotype_library.sh to download."

    candidates = index
    if domain:
        domain_col = _DOMAIN_COLUMNS.get(domain.lower())
        if domain_col:
            candidates = [
                e for e in candidates
                if e.get(domain_col) in ("1", "TRUE", "true", True)
            ]
        else:
            valid = ", ".join(sorted(_DOMAIN_COLUMNS.keys()))
            return f"Unknown domain '{domain}'. Valid domains: {valid}"

    if status:
        status_lower = status.lower()
        candidates = [
            e for e in candidates
            if status_lower in (e.get("status") or "").lower()
        ]

    scored = []
    for entry in candidates:
        score = _match_score(entry, keyword)
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda x: (-x[0], x[1].get("cohortName", "")))
    results = [entry for _, entry in scored[:limit]]

    return results, len(scored)


def get_phenotype_core(cohort_id: int) -> dict | str:
    """Retrieve a full CIRCE cohort definition JSON.

    Returns a dict with keys: cohort_id, cohort_name, status,
    logic_description, hash_tag, domains, cohort_json.
    Or an error string.
    """
    index = _load_index()

    meta = None
    for entry in index:
        if entry["cohortId"] == cohort_id:
            meta = entry
            break

    json_path = _COHORTS_DIR / f"{cohort_id}.json"

    if not json_path.exists():
        if not _COHORTS_DIR.exists():
            return "Phenotype Library data not available. Run scripts/download_phenotype_library.sh to download."
        return f"Cohort {cohort_id} not found. Use search_phenotypes to find valid IDs."

    cohort_json = json_path.read_text(encoding="utf-8")

    try:
        json.loads(cohort_json)
    except json.JSONDecodeError:
        return f"Error: Cohort {cohort_id} JSON file is malformed."

    result = {
        "cohort_id": cohort_id,
        "cohort_json": cohort_json,
    }

    if meta:
        result["cohort_name"] = meta.get("cohortName", "")
        result["status"] = meta.get("status", "")
        result["logic_description"] = meta.get("logicDescription", "")
        result["hash_tag"] = meta.get("hashTag", "")
        result["domains"] = format_domains(meta)
    else:
        result["cohort_name"] = f"Cohort {cohort_id}"

    return result
