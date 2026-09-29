"""`drift check`: compare live evidence with the registry and report what moved.

For each receipt of each selected claim this fetches fresh evidence (same handlers as `snapshot`)
and flags it when any of these hold:

- version_bump: the source reports a version different from last_version
- section_changed: the hash of the fresh excerpt differs from snapshot_hash
- lifecycle: the source itself publishes an end-of-life signal (npm deprecated, yanked or Inactive
  PyPI release, archived GitHub repo, release notes mentioning deprecation or end of life)
- stale: the claim has no valid check (a person's supported review or an automated re-check), or the
  newest one is more than STALE_DAYS (30) days old
  (on the claim's primary receipt only; fetched_at never counts as a review)
- error: the source could not be fetched or parsed (a claim we can no longer prove)

It writes reports/<run_id>.md and .json (run_id = UTC timestamp YYYY-MM-DDTHHMMSSZ, plus the scope
for partial runs) and never modifies the registry. Deciding what a change means is a human job
(`drift triage` adds JSON-only AI classification as advice).

Exit codes: 0 nothing flagged, 3 something flagged, 1 errors occurred.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import registry, report
from .fetch import FetchRefused, FetchTimeout, FetchTooLarge
from .snapshot import sha256
from .sources import SourceError, evidence_for

POLITE_DELAY_S = 0.5
EXIT_CLEAN, EXIT_ERRORS, EXIT_FLAGGED = 0, 1, 3


@dataclass
class Finding:
    id: str
    layer: int
    tool: str
    status: str
    source_type: str
    source_url: str
    on_map: bool = True
    receipt: int = 0  # 0 = the claim's primary source, n = sources[n-1]
    claim: str = ""  # claim text at check time, so triage classifies against what was checked
    reasons: list[str] = field(default_factory=list)
    old_version: str | None = None
    new_version: str | None = None
    old_hash: str | None = None
    new_hash: str | None = None
    old_excerpt: str | None = None
    new_excerpt: str | None = None
    lifecycle: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    review_state: str | None = None
    review_outcome: str | None = None
    unsupported_assertions: list[str] = field(default_factory=list)
    integrity: list[str] = field(default_factory=list)
    reviewed_at: str | None = None
    age_days: int | None = None  # days since a valid review; None = no valid review
    error: str | None = None

    @property
    def flagged(self) -> bool:
        return bool(self.reasons)

    @property
    def key(self) -> str:
        return self.id if self.receipt == 0 else f"{self.id}#{self.receipt}"


def compare(c: dict, ev, today: dt.date, receipt: int = 0) -> Finding:
    """Pure comparison of one receipt against fresh evidence. No I/O; unit-tested directly."""
    r = registry.receipts(c)[receipt]
    f = Finding(id=c["id"], layer=c["layer"], tool=c["tool"], status=c["status"],
                source_type=r["source_type"], source_url=r["source_url"], on_map=c.get("on_map", True),
                receipt=receipt, claim=c["claim"],
                old_version=r.get("last_version"), old_hash=r.get("snapshot_hash"), old_excerpt=r.get("snapshot"),
                review_state=registry.review_state(c),
                reviewed_at=str(c["reviewed_at"]) if c.get("reviewed_at") else None,
                age_days=registry.review_age_days(c, today))
    if ev is not None:
        f.new_version = ev.version
        f.new_excerpt = ev.excerpt
        f.new_hash = sha256(ev.excerpt)
        f.lifecycle = list(getattr(ev, "lifecycle", ()) or ())
        f.notes = list(getattr(ev, "notes", ()) or ())
        if ev.version and r.get("last_version") and ev.version != r["last_version"]:
            f.reasons.append("version_bump")
        if r.get("snapshot_hash") and f.new_hash != r["snapshot_hash"]:
            f.reasons.append("section_changed")
        # A lifecycle signal is flagged when it is new. Once a person has re-taken the evidence (the signal
        # text is part of the excerpt) and reviewed it, the same signal does not re-flag every week.
        if any(sig not in (r.get("snapshot") or "") for sig in f.lifecycle):
            f.reasons.append("lifecycle")
    if receipt == 0:
        # Claim-level states that an unchanged source must not hide.
        f.review_outcome = c.get("review_outcome")
        f.integrity = registry.integrity_problems(c)
        if f.integrity:
            f.reasons.append("integrity")
        if registry.review_state(c) == "valid" and c.get("review_outcome") != "supported":
            f.unsupported_assertions = registry.uncovered_assertions(c)
            f.reasons.append("unresolved_review")
        elif f.age_days is None or f.age_days > registry.STALE_DAYS:
            f.reasons.append("stale")
    return f


def check_claims(claims: list[dict], allow: frozenset[str], today: dt.date,
                 *, delay: float = POLITE_DELAY_S, log=print) -> list[Finding]:
    findings: list[Finding] = []
    for c in claims:
        for i, r in enumerate(registry.receipts(c)):
            try:
                ev = evidence_for(r, allow)
                f = compare(c, ev, today, i)
            except (FetchRefused, FetchTooLarge, FetchTimeout, SourceError) as e:
                f = compare(c, None, today, i)
                f.error = f"{type(e).__name__}: {e}"
                f.reasons.append("error")
            except Exception as e:  # network / parse errors: a claim we can no longer prove
                f = compare(c, None, today, i)
                f.error = f"{type(e).__name__}: {str(e)[:160]}"
                f.reasons.append("error")
            findings.append(f)
            log(f"{('FLAG' if f.flagged else 'ok'):5} {f.key:30} {','.join(f.reasons) or '-':32} "
                f"{(f.new_version or f.old_version or '-'):18} {(f.error or (f.new_excerpt or '')[:70])}")
            if delay:
                time.sleep(delay)
    return findings


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="drift check", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--id", action="append", help="check one claim id (repeatable)")
    ap.add_argument("--layer", type=int, help="check one layer (pre-project run)")
    ap.add_argument("--dry-run", action="store_true", help="print findings; do not write report files")
    ap.add_argument("--registry", type=Path, default=registry.REGISTRY)
    ap.add_argument("--reports-dir", type=Path, default=registry.REPORTS_DIR)
    ap.add_argument("--today", help="override today's date (YYYY-MM-DD), for tests and replays")
    ap.add_argument("--delay", type=float, default=POLITE_DELAY_S, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    claims = registry.load(args.registry)
    allow = registry.allowlist(claims)
    now = dt.datetime.now(dt.timezone.utc)
    today = dt.date.fromisoformat(args.today) if args.today else now.date()
    if args.today:  # replays keep the replayed date in the run id
        now = dt.datetime.combine(today, now.timetz())
    targets = registry.select(claims, ids=args.id, layer=args.layer)
    if not targets:
        print("no matching claims", file=sys.stderr)
        return 2

    findings = check_claims(targets, allow, today, delay=args.delay)
    scope = f"layer {args.layer}" if args.layer is not None else (f"{len(targets)} selected" if args.id else "all")
    summary = report.summarize(findings, today, scope)
    print()
    print(report.render_text_summary(summary))
    if not args.dry_run:
        meta = report.run_meta(now, scope, args.registry)
        md, js = report.write(findings, summary, args.reports_dir, meta)
        print(f"\nrun {meta['run_id']}")
        print(f"wrote {md.relative_to(registry.ROOT) if md.is_relative_to(registry.ROOT) else md}")
        print(f"wrote {js.relative_to(registry.ROOT) if js.is_relative_to(registry.ROOT) else js}")

    if summary["errors"]:
        return EXIT_ERRORS
    return EXIT_FLAGGED if summary["flagged"] else EXIT_CLEAN


def finding_dict(f: Finding) -> dict:
    d = asdict(f)
    d["key"] = f.key
    d["flagged"] = f.flagged
    return d


if __name__ == "__main__":
    sys.exit(main())
