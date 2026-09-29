"""A located excerpt of a vendor page (HTML, Markdown or JSON), whitespace-normalized."""

from __future__ import annotations

import html
import re

from ..fetch import fetch

# HTML first, deterministically. Sites that serve Markdown get an explicit .md source_url.
ACCEPT = "text/html;q=1.0, text/markdown;q=0.9, application/json;q=0.8, */*;q=0.5"
DEFAULT_EXCERPT = 240
_DROP = re.compile(r"(?is)<(script|style|noscript|svg|template)[^>]*>.*?</\1>")
_TAGS = re.compile(r"(?s)<[^>]+>")
_WS = re.compile(r"\s+")


def visible_text(body: bytes, content_type: str) -> str:
    s = body.decode("utf-8", "ignore")
    if "html" in content_type:
        s = _DROP.sub(" ", s)
        s = _TAGS.sub(" ", s)
        s = html.unescape(s)
    return _WS.sub(" ", s).strip()


def extract(text: str, locator: str, excerpt_chars: int = DEFAULT_EXCERPT) -> str:
    """Return the located excerpt or raise SourceError. excerpt_chars=0 means 'the match itself'."""
    from . import SourceError

    m = re.search(locator, text)
    if not m:
        raise SourceError(f"locator not found: {locator!r}")
    return m.group(0) if excerpt_chars == 0 else text[m.start(): m.start() + excerpt_chars]


def check(c: dict, allow: frozenset[str]):
    from . import Evidence

    r = fetch(c["source_url"], allow, accept=ACCEPT, redirect_to=c.get("redirect_to"))
    text = visible_text(r.body, r.content_type)
    excerpt = extract(text, c["locator"], c.get("excerpt_chars", DEFAULT_EXCERPT))
    return Evidence(None, excerpt)
