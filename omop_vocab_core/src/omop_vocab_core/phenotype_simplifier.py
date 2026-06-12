"""Phenotype simplification: find common parent concepts covering a seed set.

Algorithm ported from omop-graph's phenotype_simplifier.py, rewritten to use
CONCEPT_ANCESTOR table instead of broken Subsumes edge traversal.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .db import get_connection, qualified_vocab_table
from .formatting import rows_to_dicts


@dataclass
class ParentStatistics:
    """Quality metrics for a candidate parent concept."""
    concept_id: int = 0
    concept_name: str = ""
    found: set[int] = field(default_factory=set)       # seed concepts covered
    coverage: int = 0                                    # len(found)
    pollution: int = 0                                   # non-seed descendants
    completeness: float = 0.0                            # coverage / total seeds
    purity: float = 0.0                                  # coverage / (coverage + pollution)
    max_depth: int = 0                                   # deepest seed distance


def _get_direct_parents(conn, concept_ids: list[int]) -> dict[int, list[tuple[int, str]]]:
    """Get direct parents (1 level up) for a batch of concept_ids."""
    if not concept_ids:
        return {}
    placeholders = ", ".join("?" for _ in concept_ids)
    rows = conn.execute(f"""
        SELECT ca.descendant_concept_id, ca.ancestor_concept_id, c.concept_name
        FROM {qualified_vocab_table('concept_ancestor')} ca
        JOIN {qualified_vocab_table('concept')} c ON ca.ancestor_concept_id = c.concept_id
        WHERE ca.descendant_concept_id IN ({placeholders})
          AND ca.min_levels_of_separation = 1
          AND c.invalid_reason IS NULL
    """, concept_ids).fetchall()

    result: dict[int, list[tuple[int, str]]] = defaultdict(list)
    for desc_id, anc_id, anc_name in rows:
        result[desc_id].append((anc_id, anc_name))
    return result


def _count_standard_descendants(conn, parent_id: int, exclude: set[int]) -> int:
    """Count standard descendants of a parent, excluding seed concepts."""
    row = conn.execute(f"""
        SELECT COUNT(DISTINCT ca.descendant_concept_id)
        FROM {qualified_vocab_table('concept_ancestor')} ca
        JOIN {qualified_vocab_table('concept')} c ON ca.descendant_concept_id = c.concept_id
        WHERE ca.ancestor_concept_id = ?
          AND ca.min_levels_of_separation > 0
          AND c.standard_concept = 'S'
          AND c.invalid_reason IS NULL
    """, [parent_id]).fetchone()
    total_descendants = row[0] if row else 0
    # Pollution = total descendants minus the seeds we're trying to cover
    return max(0, total_descendants - len(exclude))


def validate_seeds(seed_concept_ids: list[int]) -> dict:
    """Validate seed concepts: check standard status, domains, and map non-standard seeds.

    Returns a dict with:
    - standard_seeds: list of standard seed concept dicts
    - non_standard_seeds: list of non-standard seeds with their Maps-to targets
    - warnings: list of human-readable warning strings
    - domain_mix: set of domains present across all seeds (standard + mapped)
    """
    if not seed_concept_ids:
        return {"standard_seeds": [], "non_standard_seeds": [], "warnings": [], "domain_mix": set()}

    placeholders = ", ".join("?" for _ in seed_concept_ids)
    columns = ["concept_id", "concept_name", "domain_id", "vocabulary_id",
                "concept_class_id", "standard_concept", "invalid_reason"]
    col_select = ", ".join(columns)

    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT {col_select} FROM {qualified_vocab_table('concept')} WHERE concept_id IN ({placeholders})",
            seed_concept_ids,
        ).fetchall()
        concepts = {r[0]: dict(zip(columns, r)) for r in rows}

        standard_seeds = []
        non_standard_seeds = []
        warnings = []
        all_domains = set()

        for sid in seed_concept_ids:
            c = concepts.get(sid)
            if not c:
                warnings.append(f"Concept {sid} not found in vocabulary")
                continue

            if c["standard_concept"] == "S":
                standard_seeds.append(c)
                all_domains.add(c["domain_id"])
            else:
                # Trace Maps-to for non-standard concepts
                mapped = conn.execute(f"""
                    SELECT c2.concept_id, c2.concept_name, c2.domain_id, c2.vocabulary_id,
                           c2.concept_class_id, c2.standard_concept
                    FROM {qualified_vocab_table('concept_relationship')} cr
                    JOIN {qualified_vocab_table('concept')} c2 ON cr.concept_id_2 = c2.concept_id
                    WHERE cr.concept_id_1 = ? AND cr.relationship_id = 'Maps to'
                      AND cr.invalid_reason IS NULL AND c2.concept_id != ?
                    LIMIT 1
                """, [sid, sid]).fetchone()

                entry = {
                    "seed": c,
                    "maps_to": dict(zip(
                        ["concept_id", "concept_name", "domain_id", "vocabulary_id",
                         "concept_class_id", "standard_concept"],
                        mapped,
                    )) if mapped else None,
                }
                non_standard_seeds.append(entry)

                if mapped:
                    all_domains.add(mapped[2])  # domain_id
                    warnings.append(
                        f"Seed {sid} ({c['concept_name']}) is non-standard — "
                        f"maps to {mapped[0]} ({mapped[1]}, {mapped[3]})"
                    )
                else:
                    warnings.append(
                        f"Seed {sid} ({c['concept_name']}) is non-standard with no Maps-to target"
                    )

        # Check for domain mixing
        if len(all_domains) > 1:
            warnings.append(
                f"Seeds span multiple domains: {', '.join(sorted(all_domains))}. "
                f"Common ancestor search works best within a single domain."
            )

        # Check for hierarchy mixing via mapped targets
        mapped_targets = [ns["maps_to"] for ns in non_standard_seeds if ns["maps_to"]]
        if mapped_targets and standard_seeds:
            # Check if mapped targets are in different branches than standard seeds
            std_names = {s["concept_name"] for s in standard_seeds}
            mapped_names = {m["concept_name"] for m in mapped_targets}
            if std_names & mapped_names:
                pass  # some overlap, probably fine
            else:
                target_summary = ", ".join(
                    f"{m['concept_name']} ({m['concept_id']})" for m in mapped_targets
                )
                warnings.append(
                    f"Non-standard seeds map to different concepts ({target_summary}) "
                    f"which may be in a different hierarchy branch than the standard seeds."
                )

    return {
        "standard_seeds": standard_seeds,
        "non_standard_seeds": non_standard_seeds,
        "warnings": warnings,
        "domain_mix": all_domains,
    }


def find_common_parents(
    seed_concept_ids: list[int],
    max_up_depth: int = 5,
    min_coverage: int = 2,
    compute_pollution: bool = True,
) -> list[dict]:
    """Find parent concepts that cover multiple seed concepts.

    For each candidate parent, computes:
    - coverage: how many seed concepts it subsumes
    - pollution: how many non-seed descendants it would pull in
    - completeness: coverage / total seed count
    - purity: coverage / (coverage + pollution)

    Parameters
    ----------
    seed_concept_ids : list of int
        The seed concept_ids to find common parents for.
    max_up_depth : int
        Maximum number of hierarchy levels to traverse upward (default 5).
    min_coverage : int
        Minimum number of seeds a parent must cover to be included (default 2).
    compute_pollution : bool
        Whether to compute pollution metrics. Set False for faster results
        when you only need coverage. Default True.

    Returns
    -------
    list of dict
        Candidate parents sorted by coverage (descending), then purity (descending).
    """
    if len(seed_concept_ids) < 2:
        return []

    seed_set = set(seed_concept_ids)
    candidates: dict[int, ParentStatistics] = {}

    with get_connection() as conn:
        # BFS upward from each seed
        # frontier items: (concept_id, originating_seed, depth)
        frontier = [(sid, sid, 0) for sid in seed_concept_ids]
        visited: set[tuple[int, int]] = set()

        while frontier:
            # Batch all current frontier items
            batch = []
            next_frontier = []
            for item in frontier:
                current, origin, depth = item
                if (current, origin) in visited:
                    continue
                visited.add((current, origin))
                if depth >= max_up_depth:
                    continue
                batch.append(item)

            if not batch:
                break

            # Batch-fetch parents for all frontier nodes
            frontier_ids = list({cur for cur, _, _ in batch})
            parents_map = _get_direct_parents(conn, frontier_ids)

            frontier = []
            for current, origin, depth in batch:
                for parent_id, parent_name in parents_map.get(current, []):
                    if parent_id not in candidates:
                        candidates[parent_id] = ParentStatistics(
                            concept_id=parent_id,
                            concept_name=parent_name,
                        )
                    stats = candidates[parent_id]
                    stats.found.add(origin)
                    stats.max_depth = max(stats.max_depth, depth + 1)
                    frontier.append((parent_id, origin, depth + 1))

        # Filter by min_coverage and compute metrics
        results = []
        for parent_id, stats in candidates.items():
            stats.coverage = len(stats.found)
            if stats.coverage < min_coverage:
                continue
            stats.completeness = stats.coverage / len(seed_set)

            if compute_pollution:
                stats.pollution = _count_standard_descendants(conn, parent_id, seed_set)
                denom = stats.coverage + stats.pollution
                stats.purity = stats.coverage / denom if denom > 0 else 0.0
            else:
                stats.purity = 1.0

            results.append({
                "concept_id": stats.concept_id,
                "concept_name": stats.concept_name,
                "coverage": stats.coverage,
                "pollution": stats.pollution,
                "completeness": round(stats.completeness, 3),
                "purity": round(stats.purity, 3),
                "max_depth": stats.max_depth,
                "covered_seeds": sorted(stats.found),
            })

    # Sort by coverage desc, purity desc
    results.sort(key=lambda r: (-r["coverage"], -r["purity"]))
    return results


def greedy_parent_cover(
    seed_concept_ids: list[int],
    candidates: list[dict],
    target_coverage: float = 1.0,
) -> list[dict]:
    """Select minimum set of parents that covers the seed concepts.

    Greedy set-cover: at each step, pick the candidate that covers the most
    uncovered seeds, weighted by purity.

    Parameters
    ----------
    seed_concept_ids : list of int
        The full seed set.
    candidates : list of dict
        Output from find_common_parents().
    target_coverage : float
        Stop when this fraction of seeds is covered (default 1.0 = all).

    Returns
    -------
    list of dict
        Selected parents in order of selection, each with a 'newly_covered' field.
    """
    remaining = set(seed_concept_ids)
    selected = []

    for candidate in candidates:
        candidate["_found_set"] = set(candidate.get("covered_seeds", []))

    while remaining:
        covered_so_far = len(seed_concept_ids) - len(remaining)
        if covered_so_far / max(1, len(seed_concept_ids)) >= target_coverage:
            break

        best = None
        best_gain = 0
        best_score = -1.0

        for c in candidates:
            gain_set = c["_found_set"] & remaining
            gain = len(gain_set)
            if gain < 1:
                continue
            # Score: coverage gain weighted by purity
            score = gain * c.get("purity", 1.0)
            if score > best_score:
                best_score = score
                best_gain = gain
                best = c

        if best is None:
            break

        newly_covered = sorted(best["_found_set"] & remaining)
        remaining -= best["_found_set"]

        result = {k: v for k, v in best.items() if not k.startswith("_")}
        result["newly_covered"] = newly_covered
        selected.append(result)

    return selected
