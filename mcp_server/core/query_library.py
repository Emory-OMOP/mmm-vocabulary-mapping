"""Core logic for OHDSI QueryLibrary search and retrieval."""

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data" / "query_library"

_query_index: list[dict] | None = None


def _parse_metadata(text: str) -> dict:
    meta = {}
    match = re.search(r"<!---?\s*(.*?)\s*-->", text, re.DOTALL)
    if not match:
        return meta

    block = match.group(1)
    for line in block.strip().splitlines():
        line = line.strip()
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip().lower()] = value.strip()

    return meta


def _parse_sql(text: str) -> str:
    lines = text.splitlines()
    sql_lines = []
    in_sql = False
    for line in lines:
        if line.strip().startswith("```sql"):
            in_sql = True
            continue
        if in_sql and line.strip().startswith("```"):
            break
        if in_sql:
            sql_lines.append(line.rstrip())
    return "\n".join(sql_lines)


def _parse_section(text: str, heading: str) -> str:
    pattern = rf"^## {re.escape(heading)}\s*\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def _extract_query_id(name: str) -> str:
    match = re.match(r"^([A-Z]+\d+)", name)
    return match.group(1) if match else ""


def _parse_query_file(filepath: Path) -> dict | None:
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    meta = _parse_metadata(text)
    if not meta.get("name"):
        return None

    name = meta["name"]
    query_id = _extract_query_id(name)
    display_name = name[len(query_id):].strip() if query_id else name

    sql = _parse_sql(text)
    description = _parse_section(text, "Description")
    input_section = _parse_section(text, "Input")
    output_section = _parse_section(text, "Output")

    return {
        "query_id": query_id,
        "name": display_name,
        "full_name": name,
        "group": meta.get("group", ""),
        "author": meta.get("author", ""),
        "cdm_version": meta.get("cdm version", ""),
        "description": description,
        "sql": sql,
        "input": input_section,
        "output": output_section,
        "file": str(filepath.relative_to(_DATA_DIR)),
    }


def _load_index() -> list[dict]:
    global _query_index
    if _query_index is not None:
        return _query_index

    if not _DATA_DIR.exists():
        logger.warning(
            "QueryLibrary data not found at %s. "
            "Run scripts/download_query_library.sh first.",
            _DATA_DIR,
        )
        _query_index = []
        return _query_index

    queries = []
    for md_file in sorted(_DATA_DIR.rglob("*.md")):
        parsed = _parse_query_file(md_file)
        if parsed:
            queries.append(parsed)

    _query_index = queries
    logger.info("Loaded %d query templates from QueryLibrary", len(queries))
    return _query_index


def _match_score(entry: dict, keyword: str) -> int:
    kw = keyword.lower()
    score = 0

    name = (entry.get("full_name") or "").lower()
    desc = (entry.get("description") or "").lower()
    group = (entry.get("group") or "").lower()

    if kw in name:
        score += 10
        if f" {kw}" in name or name.startswith(kw):
            score += 5
    if kw in desc:
        score += 5
    if kw in group:
        score += 3

    return score


def search_query_patterns_core(
    keyword: str,
    category: str | None = None,
    limit: int = 15,
) -> tuple[list[dict], int] | str:
    """Search QueryLibrary for SQL query templates.

    Returns (results, total_matches) on success, or an error string.
    Each result dict has query_id, name, full_name, group, cdm_version, etc.
    """
    limit = min(max(1, limit), 20)
    index = _load_index()

    if not index:
        return "Query Library data not available. Run scripts/download_query_library.sh to download."

    candidates = index
    if category:
        cat_lower = category.lower().replace("_", " ")
        candidates = [
            e for e in candidates
            if cat_lower in (e.get("group") or "").lower()
        ]

    scored = []
    for entry in candidates:
        score = _match_score(entry, keyword)
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda x: (-x[0], x[1].get("query_id", "")))
    results = [entry for _, entry in scored[:limit]]

    return results, len(scored)


def get_query_core(query_id: str) -> dict | str:
    """Retrieve a full SQL query template.

    Returns a dict with all query fields, or an error string.
    """
    index = _load_index()
    query_id_upper = query_id.upper()

    entry = None
    for e in index:
        if (e.get("query_id") or "").upper() == query_id_upper:
            entry = e
            break

    if not entry:
        if not index:
            return "Query Library data not available. Run scripts/download_query_library.sh to download."
        return f"Query '{query_id}' not found. Use search_query_patterns to find valid IDs."

    return entry
