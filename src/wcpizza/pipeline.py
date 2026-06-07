"""End-to-end pipeline orchestrator and CLI.

Stages:  fetch (OSM + Census) -> assign city -> dedupe -> classify -> rank

Usage:
    wcpizza run --states NY,NJ,CT          # live: hit Overpass + Census
    wcpizza run --source sample            # offline: use bundled fixtures
    wcpizza fetch --states NY              # cache raw sources only

Run `wcpizza --help` for all options. Outputs land in the processed dir:
    restaurants.csv  - every deduped pizzeria with its oven classification
    ranking.csv      - city-level per-capita ranking
    summary.json     - run metadata (counts, parameters, top cities)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__
from .classify import classify
from .config import Config, load_config
from .dedupe import dedupe
from .rank import rank
from .utils import HttpCache, normalize_city, write_csv, write_json

# State name -> USPS abbreviation, for normalizing OSM addr:state which may be
# either "NY" or "New York".
_STATE_NAME_TO_ABBR = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "district of columbia": "DC", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN",
    "iowa": "IA", "kansas": "KS", "kentucky": "KY", "louisiana": "LA",
    "maine": "ME", "maryland": "MD", "massachusetts": "MA", "michigan": "MI",
    "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
}
_VALID_ABBRS = set(_STATE_NAME_TO_ABBR.values())

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "data" / "sample"


def normalize_state(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    v = value.strip()
    if v.upper() in _VALID_ABBRS:
        return v.upper()
    return _STATE_NAME_TO_ABBR.get(v.lower())


# ---------------------------------------------------------------------------
# Source loading
# ---------------------------------------------------------------------------


def fetch_live(cfg: Config, states: List[str]) -> tuple[list, dict]:
    """Fetch OSM POIs and Census populations for the given states (live)."""
    from .sources import census as census_src
    from .sources import osm as osm_src

    cache = HttpCache(cfg.run.http_cache_dir)
    ua = cfg.run.user_agent

    state_abbrs = [normalize_state(s) for s in states]
    state_abbrs = [s for s in state_abbrs if s]
    # Map abbr -> full name for Overpass area lookups. title() would turn
    # "district of columbia" into "District Of Columbia", which does not match
    # the OSM name "District of Columbia", so restore the lowercase "of".
    abbr_to_name = {
        v: k.title().replace(" Of ", " of ")
        for k, v in _STATE_NAME_TO_ABBR.items()
    }

    restaurants: List[Dict[str, Any]] = []
    places: List[Dict[str, Any]] = []
    for abbr in state_abbrs:
        full = abbr_to_name[abbr]
        print(f"  [OSM] fetching pizzerias in {full} ...", file=sys.stderr)
        restaurants += osm_src.fetch_state(
            full, endpoint=cfg.osm.endpoint, cache=cache,
            amenities=list(cfg.osm.amenities), timeout=cfg.osm.timeout_s,
            user_agent=ua, sleep_after=cfg.osm.sleep_between_requests_s,
        )
        print(f"  [Census] fetching places in {abbr} ...", file=sys.stderr)
        places += census_src.fetch_state_places(
            abbr, endpoint=cfg.census.endpoint, dataset=cfg.census.dataset,
            population_variable=cfg.census.population_variable, cache=cache,
            api_key=cfg.census_api_key(), user_agent=ua,
        )

    pop_index = census_src.build_population_index(places)
    return restaurants, pop_index


def load_sample() -> tuple[list, dict]:
    """Load the bundled offline fixtures (no network)."""
    from .sources import census as census_src
    from .sources import osm as osm_src

    osm_raw = json.loads((SAMPLE_DIR / "sample_osm.json").read_text("utf-8"))
    restaurants = osm_src.parse_elements(osm_raw)

    census_raw = json.loads((SAMPLE_DIR / "sample_census.json").read_text("utf-8"))
    places = census_src.parse_places(census_raw)
    pop_index = census_src.build_population_index(places)
    return restaurants, pop_index


# ---------------------------------------------------------------------------
# Transform stages
# ---------------------------------------------------------------------------


def assign_cities(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Attach normalized (city_norm, state) to each record from its address."""
    for rec in records:
        rec["city_norm"] = normalize_city(rec.get("addr_city"))
        rec["city_display"] = rec.get("addr_city")
        rec["state"] = normalize_state(rec.get("addr_state"))
    return records


def classify_all(records: List[Dict[str, Any]], cfg: Config) -> List[Dict[str, Any]]:
    use_web = bool(cfg.classify.use_website_text)
    web_fetch = None
    if use_web:
        from .sources.website import fetch_website_text
        web_fetch = fetch_website_text

    for rec in records:
        website_text = None
        if web_fetch is not None:
            website_text = web_fetch(
                rec.get("website"), user_agent=cfg.run.user_agent,
                timeout=cfg.classify.website_fetch_timeout_s,
            )
        result = classify(
            name=rec.get("name"),
            description=rec.get("description"),
            osm_tags=rec.get("tags"),
            website_text=website_text,
        )
        rec.update(result.as_dict())
    return records


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

_RESTAURANT_FIELDS = [
    "id", "source", "name", "lat", "lon", "city_display", "city_norm",
    "state", "oven_label", "oven_confidence", "oven_evidence", "website",
    "dup_count",
]
_RANKING_FIELDS = [
    "rank", "city_display", "state", "geoid", "population", "wood_coal",
    "wood", "coal", "ambiguous", "total_pizzerias", "raw_per_100k",
    "shrunk_per_100k", "expected_wood_coal",
]


def write_outputs(cfg: Config, restaurants: List[Dict[str, Any]],
                  ranking: List[Dict[str, Any]], meta: Dict[str, Any]) -> Path:
    out_dir = Path(cfg.run.processed_dir)
    write_csv(out_dir / "restaurants.csv", restaurants, _RESTAURANT_FIELDS)
    write_csv(out_dir / "ranking.csv", ranking, _RANKING_FIELDS)
    summary = dict(meta)
    summary["top_cities"] = [
        {k: r.get(k) for k in ("rank", "city_display", "state",
                               "wood_coal", "population", "shrunk_per_100k",
                               "raw_per_100k")}
        for r in ranking[:15]
    ]
    write_json(out_dir / "summary.json", summary)
    return out_dir


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run_pipeline(cfg: Config, *, source: str, states: List[str]
                 ) -> Dict[str, Any]:
    if source == "sample":
        restaurants, pop_index = load_sample()
    else:
        if not states:
            raise SystemExit("Live runs require --states (e.g. --states NY,NJ)")
        restaurants, pop_index = fetch_live(cfg, states)

    n_raw = len(restaurants)
    restaurants = dedupe(restaurants, distance_m=cfg.dedupe.distance_m,
                         name_similarity=cfg.dedupe.name_similarity)
    n_deduped = len(restaurants)
    restaurants = assign_cities(restaurants)
    restaurants = classify_all(restaurants, cfg)

    ranking = rank(
        restaurants, pop_index,
        min_confidence=cfg.classify.min_confidence,
        min_restaurants=cfg.rank.min_restaurants,
        min_population=cfg.rank.min_population,
        per_population=cfg.rank.per_population,
        shrinkage_k=cfg.rank.shrinkage_k,
    )

    n_positive = sum(
        1 for r in restaurants
        if r.get("oven_label") in {"wood", "coal", "wood_or_coal"}
        and r.get("oven_confidence", 0) >= cfg.classify.min_confidence
    )
    meta = {
        "wcpizza_version": __version__,
        "source": source,
        "states": states,
        "raw_records": n_raw,
        "deduped_records": n_deduped,
        "wood_coal_detected": n_positive,
        "cities_ranked": len(ranking),
        "parameters": {
            "dedupe": dict(cfg.dedupe.items()),
            "classify": dict(cfg.classify.items()),
            "rank": dict(cfg.rank.items()),
        },
    }
    out_dir = write_outputs(cfg, restaurants, ranking, meta)
    meta["output_dir"] = str(out_dir)
    return meta


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wcpizza",
        description="Estimate U.S. wood/coal-fired pizza restaurants per capita.",
    )
    p.add_argument("--config", default=None, help="Path to config.yaml")
    p.add_argument("--version", action="version",
                   version=f"wcpizza {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run the full pipeline.")
    run.add_argument("--source", choices=["live", "sample"], default="live",
                     help="'live' hits Overpass + Census; 'sample' uses bundled fixtures.")
    run.add_argument("--states", default="",
                     help="Comma-separated states for live runs, e.g. NY,NJ,CT.")

    fetch = sub.add_parser("fetch", help="Only fetch & cache raw sources.")
    fetch.add_argument("--states", required=True,
                       help="Comma-separated states, e.g. NY,NJ,CT.")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)

    if args.command == "fetch":
        states = [s for s in args.states.split(",") if s.strip()]
        restaurants, pop_index = fetch_live(cfg, states)
        print(f"Fetched {len(restaurants)} OSM POIs and "
              f"{len(pop_index)} Census places into {cfg.run.http_cache_dir}")
        return 0

    if args.command == "run":
        states = [s for s in args.states.split(",") if s.strip()]
        meta = run_pipeline(cfg, source=args.source, states=states)
        print(json.dumps(meta, indent=2))
        out = Path(meta["output_dir"])
        print(f"\nWrote: {out/'ranking.csv'}\n       {out/'restaurants.csv'}"
              f"\n       {out/'summary.json'}")
        return 0

    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
