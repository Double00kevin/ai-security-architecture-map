"""npm registry, /latest document only (the full document can be tens of MB)."""

from __future__ import annotations

import re

from ..fetch import fetch
from ._common import parse_json

_NAME = re.compile(r"https://www\.npmjs\.com/package/((?:@[\w.-]+/)?[\w.-]+)/?")


def name(url: str) -> str:
    m = _NAME.fullmatch(url)
    if not m:
        from . import SourceError

        raise SourceError(f"npm source_url must be https://www.npmjs.com/package/<name>: {url}")
    return m.group(1)


def api_urls(url: str) -> list[str]:
    return [f"https://registry.npmjs.org/{name(url)}/latest"]


def check(c: dict, allow: frozenset[str]):
    from . import with_lifecycle

    n = name(c["source_url"])
    d = parse_json(fetch(f"https://registry.npmjs.org/{n}/latest", allow, accept="application/json",
                         redirect_to=c.get("redirect_to")).body)
    ver = d["version"]
    desc = (d.get("description") or "").strip()[:100]
    signals = []
    dep = d.get("deprecated")
    if dep:  # npm sets this string on a deprecated version; `true` is also seen in the wild
        signals.append(f"npm deprecated: {dep if isinstance(dep, str) else 'true'}")
    return with_lifecycle(ver, f"npm {n} {ver}: {desc}", signals)
