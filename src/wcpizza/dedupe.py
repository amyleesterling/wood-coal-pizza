"""Deduplicate restaurant records.

The same physical restaurant can appear multiple times: once as an OSM node and
once as an OSM way/relation (building footprint), across data refreshes, or
across sources. We collapse records that are both:

  * geographically close (within ``distance_m``), and
  * have similar normalized names (difflib ratio >= ``name_similarity``).

We use a simple spatial grid to keep candidate generation near-linear instead
of comparing all O(n^2) pairs, then union-find to form clusters. A
representative record is chosen per cluster (prefer the one with the richest
tags / an explicit oven tag), and we record how many raw records it absorbed.
"""
from __future__ import annotations

import math
from difflib import SequenceMatcher
from typing import Any, Dict, List, Tuple

from .utils import haversine_m, normalize_name_key


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _name_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _grid_key(lat: float, lon: float, cell_deg: float) -> Tuple[int, int]:
    return (math.floor(lat / cell_deg), math.floor(lon / cell_deg))


def _richness(rec: Dict[str, Any]) -> Tuple[int, int, int]:
    """Sort key for picking a cluster representative (higher is better)."""
    tags = rec.get("tags", {}) or {}
    has_oven = 1 if any(k in tags for k in ("oven", "fuel", "oven:fuel")) else 0
    has_site = 1 if (rec.get("website") or tags.get("website")
                     or tags.get("contact:website")) else 0
    return (has_oven, has_site, len(tags))


def dedupe(records: List[Dict[str, Any]], distance_m: float = 75.0,
           name_similarity: float = 0.87) -> List[Dict[str, Any]]:
    """Collapse duplicate restaurant records.

    Each record must have at least ``lat``, ``lon``, and ``name``. Returns a
    new list of representative records, each annotated with:
        ``dup_count``   - number of raw records in the cluster
        ``source_ids``  - list of the raw record ids merged
    """
    n = len(records)
    if n == 0:
        return []

    # ~1 cell per `distance_m`; 1 deg latitude ~ 111_320 m. We search the
    # record's cell plus 8 neighbors to catch matches that straddle a border.
    cell_deg = max(distance_m / 111_320.0, 1e-6)
    grid: Dict[Tuple[int, int], List[int]] = {}
    keys = []
    for i, rec in enumerate(records):
        k = _grid_key(rec["lat"], rec["lon"], cell_deg)
        grid.setdefault(k, []).append(i)
        keys.append(normalize_name_key(rec.get("name")))

    uf = _UnionFind(n)
    for i, rec in enumerate(records):
        gx, gy = _grid_key(rec["lat"], rec["lon"], cell_deg)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in grid.get((gx + dx, gy + dy), ()):
                    if j <= i:
                        continue
                    other = records[j]
                    if haversine_m(rec["lat"], rec["lon"],
                                   other["lat"], other["lon"]) > distance_m:
                        continue
                    if _name_similarity(keys[i], keys[j]) >= name_similarity:
                        uf.union(i, j)

    clusters: Dict[int, List[int]] = {}
    for i in range(n):
        clusters.setdefault(uf.find(i), []).append(i)

    out: List[Dict[str, Any]] = []
    for members in clusters.values():
        rep_idx = max(members, key=lambda m: _richness(records[m]))
        rep = dict(records[rep_idx])
        rep["dup_count"] = len(members)
        rep["source_ids"] = [records[m].get("id") for m in members]
        out.append(rep)
    # Deterministic ordering for reproducible output.
    out.sort(key=lambda r: (str(r.get("id")), r["lat"], r["lon"]))
    return out
