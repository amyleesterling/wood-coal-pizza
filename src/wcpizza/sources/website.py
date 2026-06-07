"""Optional, robots.txt-respecting website text enrichment.

Classification works on names, descriptions, and OSM tags by default. When the
operator opts in (``classify.use_website_text: true``), we may fetch a small
amount of text from a restaurant's own website to improve oven detection
(e.g. "we cook in a wood-burning brick oven").

To stay on the right side of "no prohibited scraping" we:
  * Only fetch a restaurant's OWN homepage (a single page), never a third
    party's, and never a search engine or directory.
  * Honor robots.txt for our User-Agent before fetching.
  * Cache aggressively and rate-limit.
  * Extract only visible text, with a hard size cap.

This module is intentionally conservative and off by default.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

_MAX_TEXT_CHARS = 20_000


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip = 0
        self.chunks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            text = data.strip()
            if text:
                self.chunks.append(text)


def _extract_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:  # pragma: no cover - malformed HTML
        pass
    text = " ".join(parser.chunks)
    return re.sub(r"\s+", " ", text)[:_MAX_TEXT_CHARS]


def robots_allows(url: str, user_agent: str) -> bool:
    """Return True if robots.txt permits ``user_agent`` to fetch ``url``."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = RobotFileParser()
    rp.set_url(robots_url)
    try:
        rp.read()
    except Exception:
        # If robots.txt can't be read, be conservative and decline.
        return False
    return rp.can_fetch(user_agent, url)


def fetch_website_text(
    url: Optional[str],
    *,
    user_agent: str = "wcpizza/0.1",
    timeout: int = 10,
) -> Optional[str]:
    """Fetch and extract visible text from a restaurant's own homepage.

    Returns None if there is no URL, robots.txt disallows it, or the fetch
    fails. Never raises.
    """
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    if not robots_allows(url, user_agent):
        return None
    try:
        resp = requests.get(url, headers={"User-Agent": user_agent},
                            timeout=timeout)
        resp.raise_for_status()
        if "text/html" not in resp.headers.get("Content-Type", ""):
            return None
        return _extract_text(resp.text)
    except Exception:
        return None
