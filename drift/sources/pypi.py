"""PyPI JSON API."""

from __future__ import annotations

import re

from ..fetch import fetch
from ._common import parse_json

_NAME = re.compile(r"https://pypi\.org/project/([A-Za-z0-9_.-]+)/?")
_DEPRECATED = re.compile(r"(?i)\bdeprecat|\bend[- ]of[- ]life\b|\bno longer maintained\b")


def name(url: str) -> str:
    m = _NAME.fullmatch(url)
    if not m:
        from . import SourceError

        raise SourceError(f"pypi source_url must be https://pypi.org/project/<name>/: {url}")
    return m.group(1)


def api_urls(url: str) -> list[str]:
    return [f"https://pypi.org/pypi/{name(url)}/json"]


def yanked_versions(d: dict) -> list[str]:
    """Versions whose every file is yanked, in the order PyPI lists them."""
    out = []
    for ver, files in (d.get("releases") or {}).items():
        if files and all(f.get("yanked") for f in files):
            out.append(ver)
    return out


def check(c: dict, allow: frozenset[str]):
    from . import with_lifecycle

    n = name(c["source_url"])
    d = parse_json(fetch(f"https://pypi.org/pypi/{n}/json", allow, accept="application/json",
                         redirect_to=c.get("redirect_to")).body)
    info = d["info"]
    ver = info["version"]
    files = d.get("releases", {}).get(ver, [])
    uploaded = files[0]["upload_time"][:10] if files else "?"
    summary = (info.get("summary") or "").strip()[:100]
    signals = []
    if info.get("yanked") or (files and all(f.get("yanked") for f in files)):
        reason = info.get("yanked_reason") or next((f.get("yanked_reason") for f in files if f.get("yanked_reason")), "")
        signals.append(f"pypi {ver} is yanked" + (f": {reason}" if reason else ""))
    notes = []
    yanked = [v for v in yanked_versions(d) if v != ver]
    if yanked:  # older yanked releases are reported, but they say nothing about the current one
        notes.append(f"pypi yanked releases: {', '.join(yanked[-5:])}" + (f" (+{len(yanked) - 5} more)" if len(yanked) > 5 else ""))
    if any("Development Status :: 7 - Inactive" in cl for cl in info.get("classifiers") or []):
        signals.append("pypi classifier: Development Status :: 7 - Inactive")
    if _DEPRECATED.search(summary):
        signals.append(f"pypi summary: {summary}")
    return with_lifecycle(ver, f"pypi {n} {ver} uploaded {uploaded}: {summary}", signals, notes)
