"""Public data source adapters.

Each module turns a sanctioned public API into a list of plain dicts the rest
of the pipeline understands. All network access goes through ``http_get`` /
``http_post`` here so caching, the User-Agent, and rate limiting are applied
uniformly.
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

import requests

from ..utils import HttpCache


def http_request(
    method: str,
    url: str,
    *,
    cache: Optional[HttpCache] = None,
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Dict[str, Any]] = None,
    user_agent: str = "wcpizza/0.1",
    timeout: int = 60,
    sleep_after: float = 0.0,
    expect: str = "json",
) -> Any:
    """Perform a cached HTTP request.

    The cache key covers method, url, and the params/body, so identical
    requests are served from disk and the pipeline is reproducible offline.
    ``expect`` is "json" or "text".
    """
    payload = {"params": params, "data": data}
    if cache is not None:
        hit = cache.get(method, url, payload)
        if hit is not None:
            return hit

    headers = {"User-Agent": user_agent}
    # Public Overpass/Census instances throttle (429) and occasionally return
    # 5xx under load. Retry transient failures with exponential backoff so a
    # multi-state run doesn't die on a single hiccup.
    max_attempts = 5
    backoff = 4.0
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.request(method, url, params=params, data=data,
                                    headers=headers, timeout=timeout)
            if resp.status_code in (429, 502, 503, 504) and attempt < max_attempts:
                raise requests.HTTPError(f"transient {resp.status_code}")
            resp.raise_for_status()
            result = resp.json() if expect == "json" else resp.text
            break
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            if attempt >= max_attempts:
                raise
            time.sleep(backoff * attempt)
    else:  # pragma: no cover - loop always breaks or raises
        raise last_exc  # type: ignore[misc]

    if cache is not None:
        cache.set(method, url, payload, result)
    if sleep_after:
        time.sleep(sleep_after)
    return result
