"""`drift snapshot`: take (or re-take) the evidence snapshot behind each claim.

For every receipt of every selected claim (the primary source and each entry of `sources:`) this
fetches the source, extracts the small piece of evidence the claim relies on (latest version, or a
located page excerpt), hashes it, and writes snapshot / snapshot_hash / last_version / fetched_at
back to registry/claims.yaml.

It never changes `claim`, `status`, `owner`, `assertions`, `supports` or the review record, and it
never creates a review. If the new evidence differs from what was reviewed, the review's hash stops
matching and the claim cannot publish until a person reads the new excerpt and runs `drift review`.

Usage:
    python -m drift snapshot --all
    python -m drift snapshot --id L02-litellm
    python -m drift snapshot --layer 6
    python -m drift snapshot --all --dry-run
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

from . import registry
from .fetch import FetchRefused, FetchTimeout, FetchTooLarge
from .sources import SourceError, evidence_for

POLITE_DELAY_S = 0.5


def sha256(s: str) -> str:
    return registry.excerpt_sha256(s)


def snapshot_receipt(r: dict, allow: frozenset[str], today: str) -> dict:
    ev = evidence_for(r, allow)
    return {
        "snapshot": ev.excerpt,
        "snapshot_hash": sha256(ev.excerpt),
        "last_version": ev.version or None,
        "fetched_at": today,
    }


def snapshot_one(c: dict, allow: frozenset[str], today: str) -> dict:  # primary receipt; kept for callers/tests
    return snapshot_receipt(registry.receipts(c)[0], allow, today)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="drift snapshot", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true")
    g.add_argument("--id", action="append")
    g.add_argument("--layer", type=int)
    ap.add_argument("--dry-run", action="store_true", help="fetch and print; do not write the registry")
    ap.add_argument("--only-missing", action="store_true", help="skip receipts that already have a snapshot")
    ap.add_argument("--registry", type=Path, default=registry.REGISTRY)
    ap.add_argument("--delay", type=float, default=POLITE_DELAY_S, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    claims = registry.load(args.registry)
    allow = registry.allowlist(claims)
    today = dt.date.today().isoformat()
    targets = claims if args.all else registry.select(claims, ids=args.id, layer=args.layer)
    if not targets:
        print("no matching claims", file=sys.stderr)
        return 2

    ok = fail = attempted = 0
    for c in targets:
        before = registry.review_state(c)
        for i, r in enumerate(registry.receipts(c)):
            if args.only_missing and r.get("snapshot"):
                continue
            attempted += 1
            label = c["id"] if i == 0 else f"{c['id']}#{i}"
            try:
                upd = snapshot_receipt(r, allow, today)
                changed = bool(r.get("snapshot_hash")) and r["snapshot_hash"] != upd["snapshot_hash"]
                print(f"{('CHANGED' if changed else 'ok'):8} {label:30} {(upd['last_version'] or '-'):18} {upd['snapshot'][:90]}")
                if not args.dry_run:
                    registry.set_receipt(c, i, upd)
                ok += 1
            except (FetchRefused, FetchTooLarge, FetchTimeout, SourceError) as e:
                print(f"{'FAIL':8} {label:30} {type(e).__name__}: {e}")
                fail += 1
            except Exception as e:  # network / parse errors: report, keep going
                print(f"{'FAIL':8} {label:30} {type(e).__name__}: {str(e)[:120]}")
                fail += 1
            if args.delay:
                time.sleep(args.delay)
        if not args.dry_run and before == "valid" and registry.review_state(c) != "valid":
            print(f"{'VOIDED':8} {c['id']:30} evidence changed since review: read it, then `python -m drift review --id {c['id']}`")

    if not args.dry_run:
        registry.save(claims, args.registry)
    print(f"\n{ok} ok, {fail} failed, {attempted} attempted")
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
