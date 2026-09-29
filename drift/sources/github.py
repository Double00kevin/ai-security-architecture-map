"""GitHub releases and tags via the REST API (unauthenticated; no token is read or needed)."""

from __future__ import annotations

import re
import urllib.error

from ..fetch import fetch
from ._common import parse_json

ACCEPT = "application/vnd.github+json"
_SLUG = re.compile(r"https://github\.com/([\w.-]+)/([\w.-]+)/?")
_EOL = re.compile(r"(?i)deprecat|end[- ]of[- ]life")


def slug(url: str) -> tuple[str, str]:
    m = _SLUG.fullmatch(url)
    if not m:
        from . import SourceError

        raise SourceError(f"github source_url must be https://github.com/<owner>/<repo>: {url}")
    return m.group(1), m.group(2)


def api_urls(url: str) -> list[str]:
    owner, repo = slug(url)
    base = f"https://api.github.com/repos/{owner}/{repo}"
    return [base, f"{base}/releases/latest", f"{base}/tags?per_page=1", f"{base}/tags?per_page=100"]


def check(c: dict, allow: frozenset[str]):
    from . import SourceError, with_lifecycle

    owner, repo = slug(c["source_url"])
    base = f"https://api.github.com/repos/{owner}/{repo}"
    rt = c.get("redirect_to")
    signals = []
    meta = parse_json(fetch(base, allow, accept=ACCEPT, redirect_to=rt).body)
    if meta.get("archived"):
        signals.append(f"github {owner}/{repo} is archived")
    if c["source_type"] == "github_release":
        try:
            rel = parse_json(fetch(f"{base}/releases/latest", allow, accept=ACCEPT, redirect_to=rt).body)
            tag = rel["tag_name"]
            m = _EOL.search(rel.get("body") or "")
            if m:
                body = rel["body"]
                a = max(0, m.start() - 60)
                snippet = " ".join(body[a:m.end() + 60].split())
                signals.append(f"release {tag} notes mention \"{m.group(0)}\": ...{snippet}...")
            return with_lifecycle(tag, f"{owner}/{repo} latest release {tag} published {rel.get('published_at', '?')}", signals)
        except urllib.error.HTTPError as e:
            if e.code != 404:  # 404 = repo has no GitHub Releases; fall through to tags
                raise
    pattern = c.get("locator")  # for github_tag, an optional regex the tag name must fully match
    per_page = 100 if pattern else 1
    tags = parse_json(fetch(f"{base}/tags?per_page={per_page}", allow, accept=ACCEPT, redirect_to=rt).body)
    names = [t["name"] for t in tags]
    if pattern:
        names = [n for n in names if re.fullmatch(pattern, n)]
    if not names:
        raise SourceError(f"{owner}/{repo}: no releases and no matching tags")
    suffix = f" (matching {pattern})" if pattern else ""
    return with_lifecycle(names[0], f"{owner}/{repo} newest tag {names[0]}{suffix}", signals)
