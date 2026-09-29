"""Registry I/O and validation for registry/claims.yaml.

A claim is what the map asserts about one tool. Its evidence is one or more receipts: the primary
receipt lives in the claim's own source_* / snapshot* fields, further receipts in `sources:`. Each
receipt says which assertions it evidences (`supports:`), and the claim lists the assertions its
text makes (`assertions:`). A claim is publishable only when every assertion has a receipt with a
snapshot that supports it.

Two kinds of dates, never mixed:
- `fetched_at` (per receipt) is written by `drift snapshot`. It says when evidence was fetched,
  nothing about whether anyone read it.
- the review record (`reviewed_at`, `reviewed_by`, `review_outcome`, `review_hash`,
  `review_claim_hash`) is written only by a person running `drift review`. `review_hash` binds the
  review to exactly what was reviewed; when the claim, its status, owner, ownership event, sources or
  evidence change, the hash no longer matches and the review is void. `review_claim_hash` binds it to
  the claim alone (everything except the excerpts' digests).
- the automated re-check (`auto_checked_at`, `auto_check_basis`, `auto_check_hash`) is written only
  by `drift auto` in the weekly job. It carries a person's `supported` review forward across routine
  evidence changes: the claim itself must be unchanged since that review (`review_claim_hash`), the
  review must be at most HUMAN_REVIEW_MAX_DAYS old when the re-check is made, and every changed
  receipt must differ only in version numbers and dates. Anything else waits for a person.

Every stored `snapshot_hash` is recomputed from its `snapshot` whenever the registry is read. A
malformed digest is a registry error; a digest that does not match its excerpt voids the claim's
review and blocks publication until `drift snapshot` re-takes the evidence and a person reviews it.
This catches accidental or partial edits. It is not a signature: someone who rewrites an excerpt and
its digest and the review hash together is not detected here (git history and review are the control).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "registry" / "claims.yaml"
REPORTS_DIR = ROOT / "reports"

SOURCE_TYPES = frozenset({"github_release", "github_tag", "pypi", "npm", "rss", "page_section"})
STATUSES = frozenset({"active", "renamed", "acquired", "deprecated", "dead"})
ASSERTIONS = ("capability", "availability", "ownership", "lifecycle")
REVIEW_OUTCOMES = ("supported", "unsupported", "partial")
OWNERSHIP_KINDS = frozenset({"acquisition_completed", "acquisition_agreed", "merger", "rename", "divestiture"})
LAYERS = range(1, 13)
LAYER_COUNTS = [10, 5, 6, 5, 5, 7, 5, 5, 5, 6, 5, 5]  # map v2 (v2026.09.27.1); v2026.09.26 was 7,4,5,5,4,6,5,5,5,6,5,5
STALE_DAYS = 30  # house rule: no review or version is trusted past 30 days
REVIEW_FETCH_MAX_DAYS = 7  # a review assesses evidence fetched on or at most this many days before it

HEADER = (
    "# Claim registry for the 12-layer AI architecture map.\n"
    "# One record per tool per layer. claim/status/owner/assertions/supports are edited by hand after\n"
    "# reading the source; snapshot fields and fetched_at are written by `python -m drift snapshot`;\n"
    "# the review record (reviewed_*, review_*) is written only by a person via `python -m drift review`.\n"
)

REQUIRED = ("id", "layer", "layer_name", "tool", "claim", "status", "source_type", "source_url")
RECEIPT_KEYS = ("source_type", "source_url", "locator", "excerpt_chars", "redirect_to",
                "snapshot", "snapshot_hash", "last_version", "fetched_at", "supports", "freshness")
REVIEW_KEYS = ("reviewed_at", "reviewed_by", "review_outcome", "review_hash", "review_claim_hash",
               "review_fetched_at", "review_event_hash")
APPROVAL_KEYS = ("approved_by", "approved_at", "approval_ref")  # optional; written only by `drift approve`
OWNER_LOGIN = "Double00kevin"  # the one GitHub account whose merge of a review PR counts as owner approval
REPOSITORY = "Double00kevin/ai-security-architecture-map"
APPROVAL_REF_RE = re.compile(r"https://github\.com/" + re.escape(REPOSITORY) + r"/pull/[1-9][0-9]*")
AUTO_KEYS = ("auto_checked_at", "auto_check_basis", "auto_check_hash")
HUMAN_REVIEW_MAX_DAYS = 180  # an automated re-check never carries a person's review further than this
LEGACY_KEYS = ("last_checked", "checked_by")  # replaced by fetched_at; never a review
ID_RE = re.compile(r"L(\d{2})-[a-z0-9]+(?:-[a-z0-9]+)*")
HASH_RE = re.compile(r"sha256:[0-9a-f]{64}")
FIELD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class RegistryError(ValueError):
    pass


# ---- receipts ----

def receipts(c: dict) -> list[dict]:
    """The claim's receipts, primary first. The primary is a live view: write through `set_receipt`."""
    primary = {k: c.get(k) for k in RECEIPT_KEYS}
    return [primary] + [dict(s) for s in (c.get("sources") or [])]


def set_receipt(c: dict, index: int, updates: dict) -> None:
    if index == 0:
        c.update(updates)
    else:
        c["sources"][index - 1].update(updates)


def _date(v) -> dt.date | None:
    if v in (None, ""):
        return None
    return v if isinstance(v, dt.date) else dt.date.fromisoformat(str(v))


# ---- evidence integrity ----

def excerpt_sha256(excerpt: str) -> str:
    return "sha256:" + hashlib.sha256(excerpt.encode("utf-8")).hexdigest()


def digest_matches(r: dict) -> bool:
    """True when the receipt holds an excerpt whose sha256 equals its stored snapshot_hash."""
    snap, h = r.get("snapshot"), r.get("snapshot_hash")
    return bool(snap) and bool(h) and excerpt_sha256(str(snap)) == h


def integrity_problems(c: dict) -> list[str]:
    """Receipts whose stored digest does not match their excerpt (evidence edited without re-taking it)."""
    out = []
    for i, r in enumerate(receipts(c)):
        if (r.get("snapshot") or r.get("snapshot_hash")) and not digest_matches(r):
            out.append(f"receipt {i} ({r['source_url']}): snapshot_hash does not match its excerpt")
    return out


# ---- review binding ----

def review_payload(c: dict) -> dict:
    """Everything a review vouches for. Change any of it and the review is void."""
    return {
        "id": c["id"],
        "layer": c["layer"],
        "tool": c["tool"],
        "claim": c["claim"],
        "status": c["status"],
        "owner": c.get("owner"),
        "ownership_event": c.get("ownership_event"),
        "assertions": sorted(c.get("assertions") or []),
        "receipts": [{"source_url": r["source_url"], "snapshot_hash": r.get("snapshot_hash"),
                      "source_type": r["source_type"], "locator": r.get("locator"),
                      "excerpt_chars": r.get("excerpt_chars"), "redirect_to": r.get("redirect_to"),
                      "supports": sorted(r.get("supports") or [])} for r in receipts(c)],
    }


def _hash(payload) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def review_hash(c: dict) -> str:
    return _hash(review_payload(c))


def claim_hash(c: dict) -> str:
    """The review payload without the excerpts' digests: what the claim says and where its proof lives."""
    p = review_payload(c)
    p["receipts"] = [{k: v for k, v in r.items() if k != "snapshot_hash"} for r in p["receipts"]]
    return _hash(p)


def _iso(v) -> str | None:
    d = _date(v)
    return None if d is None else d.isoformat()


def fetch_dates(c: dict) -> list[str | None]:
    """Each receipt's fetched_at, primary first, as YYYY-MM-DD."""
    return [_iso(r.get("fetched_at")) for r in receipts(c)]


def review_event_payload(c: dict) -> dict:
    """The review event: the claim/evidence digest it assessed plus who assessed it, when, with what
    outcome, the fetch date of every receipt it read, and the owner's approval if one was recorded.
    Change any of it and the event, and every check that rests on it, is void."""
    return {
        "review_hash": c.get("review_hash"),
        "review_claim_hash": c.get("review_claim_hash"),
        "outcome": c.get("review_outcome"),
        "assessor": c.get("reviewed_by"),
        "reviewed_at": _iso(c.get("reviewed_at")),
        "fetched_at": [_iso(d) for d in (c.get("review_fetched_at") or [])],
        "approval": {k: (None if c.get(k) in (None, "") else str(c[k])) for k in APPROVAL_KEYS},
    }


def review_event_hash(c: dict) -> str:
    return _hash(review_event_payload(c))


def review_event_intact(c: dict) -> bool:
    """The stored event digest matches the stored review record (it says nothing about current evidence)."""
    try:
        return bool(c.get("review_event_hash")) and c["review_event_hash"] == review_event_hash(c)
    except ValueError:  # an unparseable date
        return False


def review_assessment_hash(c: dict) -> str:
    """The review event without the owner's approval: what an automated re-check carries forward, so a
    later approval of the same event does not void a re-check made in between."""
    return _hash({**review_event_payload(c), "approval": None})


def auto_check_hash(c: dict) -> str:
    """The automated re-check: the current evidence digest, its date and basis, every receipt's fetch
    date, and the review assessment it carries forward."""
    return _hash({"review_hash": review_hash(c), "auto_checked_at": _iso(c.get("auto_checked_at")),
                  "basis": c.get("auto_check_basis"), "fetched_at": fetch_dates(c),
                  "review_assessment": review_assessment_hash(c)})


def owner_approved(c: dict) -> bool:
    """True only when all three approval fields are present, name the owner and a pull request of this
    repository, and the review event digest (which covers them) is intact."""
    if any(c.get(k) in (None, "") for k in APPROVAL_KEYS) or not review_event_intact(c):
        return False
    return c["approved_by"] == OWNER_LOGIN and bool(APPROVAL_REF_RE.fullmatch(str(c["approval_ref"])))


def review_state(c: dict) -> str:
    """'missing' (no review), 'void' (the reviewed evidence, claim or review event changed, a receipt's
    fetch date differs from the one assessed, or an excerpt no longer matches its stored digest), or
    'valid'."""
    if not c.get("review_hash"):
        return "missing"
    if integrity_problems(c) or not review_event_intact(c):
        return "void"
    try:
        same_fetch = [_iso(d) for d in (c.get("review_fetched_at") or [])] == fetch_dates(c)
    except ValueError:
        return "void"
    return "valid" if same_fetch and c["review_hash"] == review_hash(c) else "void"


def auto_state(c: dict) -> str:
    """'missing', 'void' or 'valid' for the automated re-check. Valid only when it matches the current
    evidence and fetch dates, the review event it carries is intact, the claim is unchanged since that
    `supported` review, and the review was at most HUMAN_REVIEW_MAX_DAYS old when the re-check was made."""
    if not c.get("auto_check_hash"):
        return "missing"
    try:
        if integrity_problems(c) or c["auto_check_hash"] != auto_check_hash(c):
            return "void"
    except ValueError:
        return "void"
    if not review_event_intact(c) or review_fetch_problems(c):
        return "void"
    if c.get("review_outcome") != "supported" or not c.get("review_claim_hash") \
            or c["review_claim_hash"] != claim_hash(c):
        return "void"
    try:
        gap = (_date(c["auto_checked_at"]) - _date(c["reviewed_at"])).days
    except (TypeError, ValueError, KeyError):
        return "void"
    return "valid" if 0 <= gap <= HUMAN_REVIEW_MAX_DAYS else "void"


def last_check(c: dict) -> tuple[dt.date | None, str | None]:
    """The newest valid check behind a claim and who made it: ('person' review or 'auto' re-check)."""
    best: tuple[dt.date | None, str | None] = (None, None)
    if review_state(c) == "valid" and c.get("review_outcome") == "supported":
        best = (_date(c["reviewed_at"]), "person")
    if auto_state(c) == "valid":
        d = _date(c["auto_checked_at"])
        if best[0] is None or d > best[0]:
            best = (d, "auto")
    return best


def fetch_window_problems(fetched: list, reviewed_at) -> list[str]:
    """Receipts whose fetch date is after the review date or more than REVIEW_FETCH_MAX_DAYS before it.
    A receipt with no fetch date and nothing fetched (None) has nothing to assess and is skipped."""
    out = []
    try:
        day = _date(reviewed_at)
    except ValueError:
        return ["review date is not YYYY-MM-DD"]
    for i, f in enumerate(fetched):
        try:
            d = _date(f)
        except ValueError:
            out.append(f"receipt {i}: fetch date {f!r} is not YYYY-MM-DD")
            continue
        if d is None or day is None:
            continue
        gap = (day - d).days
        if gap < 0:
            out.append(f"receipt {i} was fetched {d} (after the review on {day})")
        elif gap > REVIEW_FETCH_MAX_DAYS:
            out.append(f"receipt {i} was fetched {d}, {gap} days before the review on {day} "
                       f"(limit {REVIEW_FETCH_MAX_DAYS}); re-take it with `drift snapshot` and review again")
    return out


def review_fetch_problems(c: dict) -> list[str]:
    """The fetch-window rule applied to the fetch dates the review event recorded."""
    return fetch_window_problems(list(c.get("review_fetched_at") or []), c.get("reviewed_at"))


def freshness_problem(r: dict, excerpt: str | None, today: dt.date) -> str | None:
    """A receipt's optional `freshness: {field, max_age_days}` rule, for claims that are only true while
    something recent keeps happening (e.g. "updated within the last 30 days"). `field` names the JSON key
    whose ISO timestamp the excerpt holds (`"lastModified":"2026-09-27T02:00:18.000Z"`). Returns why the
    excerpt breaks the rule on `today`, or None. The rule is a check setting, not claim content: it is
    not part of the review or claim digest (adding it must not void a review; see docs/PUBLICATION.md)."""
    rule = r.get("freshness")
    if not rule:
        return None
    field, limit = rule["field"], rule["max_age_days"]
    m = re.search(r'"' + re.escape(field) + r'"\s*:\s*"([^"]+)"', excerpt or "")
    if not m:
        return f"freshness: no {field} timestamp in the excerpt"
    try:
        seen = dt.date.fromisoformat(m.group(1)[:10])
    except ValueError:
        return f"freshness: {field} {m.group(1)[:40]!r} is not an ISO date"
    age = (today - seen).days
    if age > limit:
        return f"freshness: {field} {seen} is {age} days old (limit {limit})"
    return None


def uncovered_assertions(c: dict) -> list[str]:
    """Assertions in the claim with no receipt that both supports them and holds a snapshot."""
    covered: set[str] = set()
    for r in receipts(c):
        if digest_matches(r):
            covered |= set(r.get("supports") or [])
    return [a for a in (c.get("assertions") or []) if a not in covered]


def publishable(c: dict) -> list[str]:
    """Reasons this claim cannot go on a map; empty list means it can."""
    why = []
    for i, r in enumerate(receipts(c)):
        if not r.get("snapshot") or not r.get("snapshot_hash"):
            why.append(f"receipt {i} ({r['source_url']}) has no snapshot/hash")
    why += integrity_problems(c)
    if not c.get("assertions"):
        why.append("claim lists no assertions")
    missing = uncovered_assertions(c)
    if missing:
        why.append(f"no supporting receipt for: {', '.join(missing)}")
    state = review_state(c)
    if state == "valid":
        if c.get("review_outcome") != "supported":
            why.append(f"review outcome is {c.get('review_outcome')!r}, not 'supported'")
        why += review_fetch_problems(c)
    elif auto_state(c) != "valid":
        why.append(f"review {state}" + ("" if state == "missing" else " and no valid automated re-check"))
    return why


# ---- validation ----

def _validate_receipt(cid: str, i: int, r: dict) -> None:
    where = f"{cid} receipt {i}"
    if r.get("source_type") not in SOURCE_TYPES:
        raise RegistryError(f"{where}: bad source_type {r.get('source_type')}")
    if not str(r.get("source_url") or "").startswith("https://"):
        raise RegistryError(f"{cid}: source_url must be https" if i == 0 else f"{where}: source_url must be https")
    if r["source_type"] == "page_section" and not r.get("locator"):
        raise RegistryError(f"{cid}: page_section needs a locator" if i == 0 else f"{where}: page_section needs a locator")
    if r.get("redirect_to") is not None and not str(r["redirect_to"]).startswith("https://"):
        raise RegistryError(f"{cid}: redirect_to must be https")
    bad = set(r.get("supports") or []) - set(ASSERTIONS)
    if bad:
        raise RegistryError(f"{where}: unknown supports {sorted(bad)}")
    h = r.get("snapshot_hash")
    if h not in (None, "") and not HASH_RE.fullmatch(str(h)):
        raise RegistryError(f"{where}: snapshot_hash must look like sha256:<64 lowercase hex>, got {str(h)[:40]!r}")
    try:
        _date(r.get("fetched_at"))
    except ValueError:
        raise RegistryError(f"{where}: fetched_at must be YYYY-MM-DD") from None
    rule = r.get("freshness")
    if rule is not None:
        ok = (isinstance(rule, dict) and set(rule) == {"field", "max_age_days"}
              and isinstance(rule["field"], str) and FIELD_RE.fullmatch(rule["field"])
              and type(rule["max_age_days"]) is int and rule["max_age_days"] > 0)
        if not ok:
            raise RegistryError(f"{where}: freshness must be {{field: <json key>, max_age_days: <positive int>}}")


def validate(claims: list[dict]) -> list[str]:
    """Raise RegistryError on a malformed registry. Returns the ids whose review is void (the hash no
    longer matches what is in the registry, or an excerpt no longer matches its digest); a void review
    is legal, it just cannot publish."""
    seen: set[str] = set()
    on_map_keys: set[tuple[int, str]] = set()
    void = []
    for c in claims:
        missing = [k for k in REQUIRED if k not in c]
        if missing:
            raise RegistryError(f"{c.get('id', '?')}: missing {missing}")
        cid = c["id"]
        if cid in seen:
            raise RegistryError(f"duplicate id {cid}")
        seen.add(cid)
        legacy = [k for k in LEGACY_KEYS if k in c]
        if legacy:
            raise RegistryError(f"{cid}: legacy field(s) {legacy}; last_checked is now fetched_at and is never a review")
        if not isinstance(c["layer"], int) or isinstance(c["layer"], bool) or c["layer"] not in LAYERS:
            raise RegistryError(f"{cid}: layer must be an integer 1..12, got {c['layer']!r}")
        m = ID_RE.fullmatch(cid)
        if not m or int(m.group(1)) != c["layer"]:
            raise RegistryError(f"{cid}: id must look like L{c['layer']:02d}-<slug>")
        if c["status"] not in STATUSES:
            raise RegistryError(f"{cid}: bad status {c['status']}")
        if not isinstance(c.get("on_map", True), bool):
            raise RegistryError(f"{cid}: on_map must be true/false")
        if c["source_type"] not in SOURCE_TYPES:
            raise RegistryError(f"{cid}: bad source_type {c['source_type']}")
        for i, r in enumerate(receipts(c)):
            _validate_receipt(cid, i, r)
        bad = set(c.get("assertions") or []) - set(ASSERTIONS)
        if bad:
            raise RegistryError(f"{cid}: unknown assertions {sorted(bad)}")
        ev = c.get("ownership_event")
        if ev is not None:
            if not isinstance(ev, dict) or ev.get("kind") not in OWNERSHIP_KINDS or not ev.get("counterparty"):
                raise RegistryError(f"{cid}: ownership_event needs kind in {sorted(OWNERSHIP_KINDS)} and a counterparty")
            if not str(ev.get("source_url") or "").startswith("https://"):
                raise RegistryError(f"{cid}: ownership_event.source_url must be https")
            try:
                _date(ev.get("date"))
            except ValueError:
                raise RegistryError(f"{cid}: ownership_event.date must be YYYY-MM-DD") from None
            if not any(r["source_url"] == ev["source_url"] and "ownership" in (r.get("supports") or [])
                       for r in receipts(c)):
                raise RegistryError(f"{cid}: ownership_event.source_url must be one of the claim's receipts, supporting ownership")
        if (c.get("owner") or ev) and "ownership" not in (c.get("assertions") or []):
            raise RegistryError(f"{cid}: owner/ownership_event recorded but 'ownership' is not in assertions")
        present = [k for k in REVIEW_KEYS if c.get(k) not in (None, "")]
        if present:
            if len(present) != len(REVIEW_KEYS):
                raise RegistryError(f"{cid}: incomplete review record (has {present})")
            if c["review_outcome"] not in REVIEW_OUTCOMES:
                raise RegistryError(f"{cid}: review_outcome must be one of {REVIEW_OUTCOMES}")
            try:
                _date(c["reviewed_at"])
            except ValueError:
                raise RegistryError(f"{cid}: reviewed_at must be YYYY-MM-DD") from None
            rf = c["review_fetched_at"]
            if not isinstance(rf, list):
                raise RegistryError(f"{cid}: review_fetched_at must be a list of YYYY-MM-DD, one per receipt")
            try:
                [_date(d) for d in rf]
            except ValueError:
                raise RegistryError(f"{cid}: review_fetched_at must be a list of YYYY-MM-DD") from None
            if not HASH_RE.fullmatch(str(c["review_event_hash"])):
                raise RegistryError(f"{cid}: review_event_hash must look like sha256:<64 lowercase hex>")
            if review_state(c) == "void" and auto_state(c) != "valid":
                void.append(cid)
        approval = [k for k in APPROVAL_KEYS if c.get(k) not in (None, "")]
        if approval:
            if len(approval) != len(APPROVAL_KEYS) or not present:
                raise RegistryError(f"{cid}: incomplete owner approval (has {approval}); only `drift approve` writes it")
            if c["approved_by"] != OWNER_LOGIN or not APPROVAL_REF_RE.fullmatch(str(c["approval_ref"])):
                raise RegistryError(f"{cid}: approval must name {OWNER_LOGIN} and a pull request of {REPOSITORY}")
            try:
                approved = _date(c["approved_at"])
            except ValueError:
                raise RegistryError(f"{cid}: approved_at must be YYYY-MM-DD") from None
            if approved < _date(c["reviewed_at"]):
                raise RegistryError(f"{cid}: approved_at {approved} is before the review it approves")
        auto_present = [k for k in AUTO_KEYS if c.get(k) not in (None, "")]
        if auto_present:
            if len(auto_present) != len(AUTO_KEYS):
                raise RegistryError(f"{cid}: incomplete automated re-check record (has {auto_present})")
            try:
                _date(c["auto_checked_at"])
            except ValueError:
                raise RegistryError(f"{cid}: auto_checked_at must be YYYY-MM-DD") from None
        if c.get("on_map", True):
            key = (c["layer"], c["tool"])
            if key in on_map_keys:
                raise RegistryError(f"duplicate on-map tool {c['tool']!r} in layer {c['layer']}")
            on_map_keys.add(key)
    return void


def on_map(claims: list[dict]) -> list[dict]:
    """Claims that appear on the current map version. Others are verified candidates (receipts only)."""
    return [c for c in claims if c.get("on_map", True)]


def layer_counts(claims: list[dict]) -> list[int]:
    return [sum(1 for c in claims if c["layer"] == i) for i in LAYERS]


def load(path: Path = REGISTRY) -> list[dict]:
    with Path(path).open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    claims = data["claims"]
    validate(claims)
    return claims


def save(claims: list[dict], path: Path = REGISTRY) -> None:
    validate(claims)
    with Path(path).open("w", encoding="utf-8", newline="\n") as f:
        f.write(HEADER)
        yaml.safe_dump({"claims": claims}, f, sort_keys=False, allow_unicode=True, width=100)


def file_sha256(path: Path = REGISTRY) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def allowlist(claims: list[dict]) -> frozenset[str]:
    """Every URL the checker may touch, derived from the registry alone."""
    from .sources import api_urls  # local import: sources imports nothing from here

    urls: set[str] = set()
    for c in claims:
        for r in receipts(c):
            urls.add(r["source_url"])
            urls.update(api_urls(r))
            if r.get("redirect_to"):
                urls.add(r["redirect_to"])
    return frozenset(urls)


def select(claims: list[dict], *, ids: list[str] | None = None, layer: int | None = None) -> list[dict]:
    out = claims
    if ids:
        want = set(ids)
        out = [c for c in out if c["id"] in want]
    if layer is not None:
        out = [c for c in out if c.get("layer") == layer]
    return out


def review_age_days(c: dict, today: dt.date) -> int | None:
    """Days since the newest valid check (a person's supported review or a valid automated re-check).
    None when there is none."""
    d, _ = last_check(c)
    return None if d is None else (today - d).days
