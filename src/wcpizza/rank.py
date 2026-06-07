"""Compute city-level per-capita rankings.

Given classified, deduplicated restaurants (each assigned to a city) and a
population table, we count wood/coal pizzerias per city and divide by
population.

Naive per-capita rates are dominated by tiny places, so we apply two guards:

  * Hard filters: minimum restaurant count and minimum population.
  * Empirical-Bayes shrinkage: we pull each city's rate toward the national
    average with strength ``shrinkage_k`` (a pseudo-count). This is what
    "Bayesian average" rating systems do; it prevents a single pizzeria in a
    20k-person town from topping a real pizza city. The headline ranking uses
    the shrunk rate; the raw rate is reported alongside for transparency.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .classify import POSITIVE_LABELS


def _city_key(rec: Dict[str, Any]) -> Optional[tuple]:
    city = rec.get("city_norm")
    state = rec.get("state")
    if not city or not state:
        return None
    return (city, state)


def aggregate_counts(restaurants: List[Dict[str, Any]],
                     min_confidence: float) -> Dict[tuple, Dict[str, Any]]:
    """Count positive (wood/coal) restaurants per (city, state)."""
    agg: Dict[tuple, Dict[str, Any]] = {}
    for rec in restaurants:
        key = _city_key(rec)
        if key is None:
            continue
        bucket = agg.setdefault(key, {
            "city_norm": key[0], "state": key[1],
            "city_display": rec.get("city_display") or key[0],
            "wood_coal": 0, "wood": 0, "coal": 0, "ambiguous": 0,
            "total_pizzerias": 0,
        })
        bucket["total_pizzerias"] += 1
        label = rec.get("oven_label")
        conf = rec.get("oven_confidence", 0.0)
        if label in POSITIVE_LABELS and conf >= min_confidence:
            bucket["wood_coal"] += 1
            if label == "wood":
                bucket["wood"] += 1
            elif label == "coal":
                bucket["coal"] += 1
            else:
                bucket["ambiguous"] += 1
    return agg


def rank(
    restaurants: List[Dict[str, Any]],
    population: Dict[tuple, Dict[str, Any]],
    *,
    min_confidence: float = 0.5,
    min_restaurants: int = 3,
    min_population: int = 20_000,
    per_population: int = 100_000,
    shrinkage_k: float = 5.0,
) -> List[Dict[str, Any]]:
    """Produce a ranked list of cities by wood/coal pizzerias per capita.

    ``population`` maps (city_norm, state) -> {"population": int,
    "place_display": str, "geoid": str}. States must match between the
    restaurant records and the population table (use 2-letter codes in both).
    """
    agg = aggregate_counts(restaurants, min_confidence)

    # National average rate (per person) over the cities we can match, used as
    # the shrinkage prior.
    tot_wc = 0
    tot_pop = 0
    enriched: List[Dict[str, Any]] = []
    for key, bucket in agg.items():
        pop_row = population.get(key)
        if not pop_row:
            continue
        pop = pop_row.get("population")
        if not pop or pop <= 0:
            continue
        row = dict(bucket)
        row["population"] = int(pop)
        row["geoid"] = pop_row.get("geoid")
        row["city_display"] = pop_row.get("place_display") or bucket["city_display"]
        enriched.append(row)
        tot_wc += bucket["wood_coal"]
        tot_pop += int(pop)

    prior_rate = (tot_wc / tot_pop) if tot_pop else 0.0  # wood/coal per person

    # Pseudo-population that, at the national rate, would yield `shrinkage_k`
    # wood/coal restaurants. Adding it to every city implements empirical-Bayes
    # shrinkage toward the national rate (strong for small cities, negligible
    # for large ones).
    alpha_pop = (shrinkage_k / prior_rate) if (shrinkage_k > 0 and prior_rate > 0) else 0.0

    results: List[Dict[str, Any]] = []
    for row in enriched:
        pop = row["population"]
        wc = row["wood_coal"]
        raw_rate = wc / pop * per_population
        if alpha_pop > 0:
            shrunk = (wc + shrinkage_k) / (pop + alpha_pop) * per_population
        else:
            shrunk = raw_rate
        row["raw_per_100k"] = round(raw_rate, 4)
        row["shrunk_per_100k"] = round(shrunk, 4)
        row["expected_wood_coal"] = round(prior_rate * pop, 2)
        results.append(row)

    # Apply display filters AFTER computing the prior from all matched cities.
    filtered = [
        r for r in results
        if r["wood_coal"] >= min_restaurants and r["population"] >= min_population
    ]

    filtered.sort(key=lambda r: (-r["shrunk_per_100k"], -r["wood_coal"],
                                 r["city_display"]))
    for i, r in enumerate(filtered, start=1):
        r["rank"] = i
    return filtered
