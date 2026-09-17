"""Fetch a recipe web page and reduce it to plain text.

``fetch_html`` returns raw HTML (also used for JSON-LD extraction);
``fetch_page`` returns reduced text sized for small-context LLMs.
A generic browser User-Agent is the default; override it per call if
a site blocks it.
"""

from __future__ import annotations

import re
import urllib.request

MAX_CHARS = 20_000

DEFAULT_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) Gecko/20100101 Firefox/128.0"


class FetchError(Exception):
    """Raised when a page cannot be fetched."""


def fetch_html(url: str, user_agent: str = DEFAULT_USER_AGENT) -> str:
    """Fetch a URL and return the raw HTML."""
    request = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise FetchError(f"Could not fetch {url}: {exc}") from exc


def fetch_page(
    url: str,
    max_chars: int = MAX_CHARS,
    user_agent: str = DEFAULT_USER_AGENT,
) -> str:
    """Fetch a URL and return reduced plain text (small-context friendly)."""
    return page_to_text(fetch_html(url, user_agent), max_chars)


def page_to_text(html: str, max_chars: int = MAX_CHARS) -> str:
    """Strip scripts, styles, and tags; collapse whitespace; truncate."""
    html = re.sub(
        r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I
    )
    html = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", html)
    return text[:max_chars]
