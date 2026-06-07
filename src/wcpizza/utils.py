"""Shared helpers: geodesy, text normalization, and a tiny disk HTTP cache.

These are deliberately dependency-free (standard library only) so the core of
the pipeline can be tested and run anywhere without installing scientific
packages.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
import unicodedata
from pathlib import Path
from typing import Any, Dict, Optional

# ---------------------------------------------------------------------------
# Geodesy
# ---------------------------------------------------------------------------

EARTH_RADIUS_M = 6_371_000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters between two WGS84 points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------------

# Tokens that carry no identity signal for a restaurant name and only add noise
# to fuzzy matching / dedup.
_NAME_STOPWORDS = {
    "the", "a", "an", "of", "and", "co", "company", "llc", "inc",
    "restaurant", "ristorante", "pizzeria", "pizza", "pizzas",
    "trattoria", "cafe", "caffe", "bar", "grill", "kitchen", "house",
}

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def strip_accents(text: str) -> str:
    """Fold accented characters to ASCII (café -> cafe)."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def normalize_text(text: Optional[str]) -> str:
    """Lowercase, de-accent, strip punctuation, collapse whitespace."""
    if not text:
        return ""
    text = strip_accents(text).lower()
    text = _PUNCT_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def normalize_name_key(name: Optional[str]) -> str:
    """A canonical, stop-word-removed key for matching restaurant names.

    "Tony's Coal Fired Pizza, LLC" -> "tonys coal fired"
    """
    norm = normalize_text(name)
    tokens = [t for t in norm.split() if t not in _NAME_STOPWORDS]
    return " ".join(tokens)


def normalize_city(name: Optional[str]) -> str:
    """Normalize a city name for joining OSM addr:city to Census place names.

    Census place names look like "New York city, New York" or "Nashville-
    Davidson metropolitan government (balance), Tennessee"; OSM addr:city is
    usually just "New York". We strip the trailing state, common Census place
    suffixes, and normalize text.
    """
    if not name:
        return ""
    # Drop a trailing ", State" if present (Census NAME field).
    name = name.split(",")[0]
    norm = normalize_text(name)
    for suffix in (" city", " town", " village", " borough", " cdp",
                   " municipality", " metro government", " balance"):
        if norm.endswith(suffix):
            norm = norm[: -len(suffix)].strip()
    return norm


# ---------------------------------------------------------------------------
# Disk-backed HTTP cache
# ---------------------------------------------------------------------------


class HttpCache:
    """A minimal content-addressed response cache.

    Keyed by a stable hash of (method, url, params, body). Storing every raw
    response on disk makes the whole pipeline reproducible: a re-run reads the
    exact same upstream bytes instead of re-querying live services that change
    over time. Delete the cache dir to force a refresh.
    """

    def __init__(self, cache_dir: str | Path):
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _key(method: str, url: str, payload: Any) -> str:
        blob = json.dumps(
            {"m": method.upper(), "u": url, "p": payload},
            sort_keys=True, ensure_ascii=False,
        )
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def path_for(self, method: str, url: str, payload: Any) -> Path:
        return self.dir / f"{self._key(method, url, payload)}.json"

    def get(self, method: str, url: str, payload: Any) -> Optional[Any]:
        p = self.path_for(method, url, payload)
        if p.exists():
            with open(p, "r", encoding="utf-8") as fh:
                return json.load(fh)["response"]
        return None

    def set(self, method: str, url: str, payload: Any, response: Any) -> None:
        p = self.path_for(method, url, payload)
        record = {"meta": {"method": method, "url": url, "payload": payload,
                           "cached_at": time.time()},
                  "response": response}
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(record, fh, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Small IO helpers
# ---------------------------------------------------------------------------


def write_json(path: str | Path, obj: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2)


def read_json(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def write_csv(path: str | Path, rows: list[Dict[str, Any]], fieldnames: list[str]) -> None:
    import csv

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
