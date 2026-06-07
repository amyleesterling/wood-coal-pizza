"""OpenStreetMap pizza POIs via the Overpass API.

Why this source:
  * OpenStreetMap data is openly licensed (ODbL). Attribution is required;
    see METHODOLOGY.md.
  * The Overpass API is a *sanctioned, documented query interface* to OSM —
    using it is not "scraping" a website, and it does not violate any site's
    terms. (We still rate-limit and cache to be a good citizen of the free
    public instance.)

We pull food-service POIs that look pizza-related and keep the tags we need:
name, location, address (for city assignment), website, description, and any
explicit `oven` / `fuel` tags.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..utils import HttpCache
from . import http_request

# Overpass QL. For a given area we select nodes/ways/relations that are
# restaurants/fast_food/cafes AND look pizza-related (cuisine contains pizza or
# the name contains pizza/pizzeria). `out center` gives ways/relations a
# representative lat/lon.
_QUERY_TEMPLATE = """
[out:json][timeout:{timeout}];
{area_clause}
(
  nwr["amenity"~"^({amenities})$"]["cuisine"~"pizza",i]{area_filter};
  nwr["amenity"~"^({amenities})$"]["name"~"pizz",i]{area_filter};
);
out center tags;
"""


def build_query(
    *,
    area_name: Optional[str] = None,
    admin_level: int = 4,
    bbox: Optional[tuple] = None,
    amenities: Optional[List[str]] = None,
    timeout: int = 180,
) -> str:
    """Construct an Overpass QL query.

    Provide exactly one geographic scope:
      * ``area_name`` (e.g. a state name) + ``admin_level`` (4 = US state), or
      * ``bbox`` = (south, west, north, east).
    """
    amenities = amenities or ["restaurant", "fast_food", "cafe"]
    amen = "|".join(amenities)

    if area_name:
        area_clause = (
            f'area["name"="{area_name}"]["admin_level"="{admin_level}"]'
            f'["boundary"="administrative"]->.searchArea;'
        )
        area_filter = "(area.searchArea)"
    elif bbox:
        s, w, n, e = bbox
        area_clause = ""
        area_filter = f"({s},{w},{n},{e})"
    else:
        raise ValueError("Provide either area_name or bbox")

    return _QUERY_TEMPLATE.format(
        timeout=timeout, amenities=amen,
        area_clause=area_clause, area_filter=area_filter,
    )


def parse_elements(overpass_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Turn a raw Overpass JSON response into normalized restaurant records."""
    out: List[Dict[str, Any]] = []
    for el in overpass_json.get("elements", []):
        tags = el.get("tags", {}) or {}
        # Node has lat/lon directly; way/relation have it under "center".
        lat = el.get("lat", (el.get("center") or {}).get("lat"))
        lon = el.get("lon", (el.get("center") or {}).get("lon"))
        if lat is None or lon is None:
            continue
        name = tags.get("name")
        if not name:
            continue
        out.append({
            "id": f'osm:{el.get("type")}/{el.get("id")}',
            "source": "osm",
            "name": name,
            "lat": float(lat),
            "lon": float(lon),
            "addr_city": tags.get("addr:city"),
            "addr_state": tags.get("addr:state"),
            "website": (tags.get("website") or tags.get("contact:website")
                        or tags.get("url")),
            "description": tags.get("description"),
            "cuisine": tags.get("cuisine"),
            "tags": tags,
        })
    return out


def fetch_state(
    state_name: str,
    *,
    endpoint: str,
    cache: HttpCache,
    amenities: Optional[List[str]] = None,
    timeout: int = 180,
    user_agent: str = "wcpizza/0.1",
    sleep_after: float = 5.0,
) -> List[Dict[str, Any]]:
    """Fetch and parse all pizza POIs for one US state (admin_level=4)."""
    query = build_query(area_name=state_name, admin_level=4,
                        amenities=amenities, timeout=timeout)
    raw = http_request(
        "POST", endpoint, cache=cache, data={"data": query},
        user_agent=user_agent, timeout=timeout + 30, sleep_after=sleep_after,
    )
    return parse_elements(raw)
