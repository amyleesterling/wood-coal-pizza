"""City population from the U.S. Census Bureau Data API.

Why this source:
  * U.S. government works are public domain; the Census Data API is the
    authoritative, free, programmatic source for population.
  * We use the ACS 5-year estimates, variable B01003_001E (total population),
    at the "place" summary level. A Census "place" (incorporated places +
    census designated places) is the unit closest to a colloquial "city".

We return a mapping keyed by (normalized_city, state_abbr) so it joins cleanly
to OSM ``addr:city`` / ``addr:state`` values.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..utils import HttpCache, normalize_city
from . import http_request

# FIPS state code -> USPS abbreviation (50 states + DC).
STATE_FIPS_TO_ABBR = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO",
    "09": "CT", "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI",
    "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
    "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN",
    "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
    "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
    "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA",
    "54": "WV", "55": "WI", "56": "WY",
}

ABBR_TO_STATE_FIPS = {v: k for k, v in STATE_FIPS_TO_ABBR.items()}


def parse_places(rows: List[List[str]]) -> List[Dict[str, Any]]:
    """Parse a Census API JSON array (first row is the header)."""
    if not rows:
        return []
    header = rows[0]
    idx = {name: i for i, name in enumerate(header)}
    out: List[Dict[str, Any]] = []
    for row in rows[1:]:
        name = row[idx["NAME"]]              # e.g. "Chicago city, Illinois"
        pop_raw = row[idx[_pop_col(header)]]
        state_fips = row[idx["state"]]
        place_fips = row[idx["place"]]
        try:
            population = int(float(pop_raw))
        except (TypeError, ValueError):
            continue
        abbr = STATE_FIPS_TO_ABBR.get(state_fips)
        if not abbr:
            continue
        out.append({
            "place_display": name,
            "city_norm": normalize_city(name),
            "state": abbr,
            "population": population,
            "geoid": f"{state_fips}{place_fips}",
        })
    return out


def _pop_col(header: List[str]) -> str:
    # The population variable column (anything starting with B01003 or P1_).
    for h in header:
        if h.upper().startswith(("B01003", "P1_", "P001", "DP05")):
            return h
    raise ValueError(f"No population column found in header: {header}")


def fetch_state_places(
    state_abbr: str,
    *,
    endpoint: str,
    dataset: str,
    population_variable: str,
    cache: HttpCache,
    api_key: Optional[str] = None,
    user_agent: str = "wcpizza/0.1",
) -> List[Dict[str, Any]]:
    """Fetch all places (cities) and populations for one state."""
    fips = ABBR_TO_STATE_FIPS.get(state_abbr.upper())
    if not fips:
        raise ValueError(f"Unknown state abbreviation: {state_abbr}")
    url = f"{endpoint.rstrip('/')}/{dataset}"
    params = {
        "get": f"NAME,{population_variable}",
        "for": "place:*",
        "in": f"state:{fips}",
    }
    if api_key:
        params["key"] = api_key
    rows = http_request("GET", url, cache=cache, params=params,
                        user_agent=user_agent, timeout=60)
    return parse_places(rows)


def build_population_index(
    places: List[Dict[str, Any]]
) -> Dict[tuple, Dict[str, Any]]:
    """Index places by (city_norm, state). On a name collision within a state
    (rare for places), keep the most populous to match colloquial usage."""
    index: Dict[tuple, Dict[str, Any]] = {}
    for p in places:
        key = (p["city_norm"], p["state"])
        existing = index.get(key)
        if existing is None or p["population"] > existing["population"]:
            index[key] = p
    return index
