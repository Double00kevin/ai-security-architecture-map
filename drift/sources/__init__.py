"""Source handlers. Each returns Evidence(version, excerpt, lifecycle) for one receipt.

A handler receives the receipt record (the claim's primary source, or one entry of `sources:`) and
the fetch allowlist, fetches only the URLs `api_urls()` derived for it (or its own source_url), and
returns a short piece of evidence. Handlers never decide what a change means.

`lifecycle` carries signals the source itself publishes about the end of a tool's life: an npm
`deprecated` field, a yanked or "Inactive" PyPI release, an archived GitHub repository, a release
body that mentions deprecation or end of life. A signal is appended to the excerpt (so the hash
moves) and becomes its own `lifecycle` reason in `drift check`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Evidence:
    version: str | None  # unambiguous version string when the source has one, else None
    excerpt: str  # short human-readable evidence; this is what gets hashed
    lifecycle: tuple[str, ...] = ()  # end-of-life signals published by the source itself
    notes: tuple[str, ...] = ()  # reported, not hashed, not a flag (e.g. older yanked releases)


def with_lifecycle(version: str | None, excerpt: str, signals: list[str], notes: list[str] = ()) -> "Evidence":
    """Excerpts without signals stay byte-identical to before, so existing hashes keep matching."""
    signals = [s[:160] for s in signals]
    if signals:
        excerpt = f"{excerpt} | LIFECYCLE: {'; '.join(signals)}"
    return Evidence(version, excerpt, tuple(signals), tuple(n[:200] for n in notes))


class SourceError(Exception):
    """The source answered, but not in a way we can use (no tags, locator missing, bad JSON)."""


from . import github, npm, page_section, pypi, rss  # noqa: E402

HANDLERS: dict[str, Callable[[dict, frozenset[str]], Evidence]] = {
    "github_release": github.check,
    "github_tag": github.check,
    "pypi": pypi.check,
    "npm": npm.check,
    "rss": rss.check,
    "page_section": page_section.check,
}


def api_urls(c: dict) -> list[str]:
    """API endpoints a handler may need for this claim, derived from its human-readable source_url."""
    t = c["source_type"]
    if t in ("github_release", "github_tag"):
        return github.api_urls(c["source_url"])
    if t == "pypi":
        return pypi.api_urls(c["source_url"])
    if t == "npm":
        return npm.api_urls(c["source_url"])
    return []


def evidence_for(c: dict, allow: frozenset[str]) -> Evidence:
    return HANDLERS[c["source_type"]](c, allow)
