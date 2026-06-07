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
    # 5xx under load. Retry those transient failures with exponential backoff so
    # a multi-state run doesn't die on a single hiccup. A 2xx with a non-JSON
    # body (e.g. the Census "a valid key is required" message returned to
    # rate-limited keyless callers) is deterministic, so we fail fast on it
    # rather than burning the full backoff budget on every state.
    max_attempts = 5
    backoff = 4.0
    for attempt in range(1, max_attempts + 1):
        try:
            resp = requests.request(method, url, params=params, data=data,
                                    headers=headers, timeout=timeout)
            if resp.status_code in (429, 502, 503, 504) and attempt < max_attempts:
                raise requests.HTTPError(f"transient {resp.status_code}")
            resp.raise_for_status()
            break
        except requests.RequestException:
            if attempt >= max_attempts:
                raise
            time.sleep(backoff * attempt)

    if expect == "json":
        try:
            result = resp.json()
        except ValueError as exc:
            snippet = (resp.text or "").strip()[:200]
            raise ValueError(
                f"Non-JSON response from {url} (HTTP {resp.status_code}): "
                f"{snippet!r}"
            ) from exc
    else:
        result = resp.text

    if cache is not None:
        cache.set(method, url, payload, result)
    if sleep_after:
        time.sleep(sleep_after)
    return result
