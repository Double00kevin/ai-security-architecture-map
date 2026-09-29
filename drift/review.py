"""`drift review`: record that a person read a claim's evidence, and what they concluded.

    python -m drift review --status                      # every claim: review state, why it can't publish
    python -m drift review --id L02-litellm --outcome supported --by <name>

This is the only command that writes the review record (reviewed_at, reviewed_by, review_outcome,
review_hash, review_claim_hash). It is never run by `check`, `snapshot`, `triage`, `auto` or the
weekly job. Run it only after
reading every receipt's excerpt for the claim and deciding whether it supports each assertion in the
claim text.

`review_hash` covers the claim text, tool, layer, status, owner, ownership event, assertions, and
every receipt's source_url, source type, extraction/redirect settings, snapshot_hash and supports list. Change any of them and the review is
void until someone reviews again.

An outcome of `supported` is refused when a receipt has no snapshot or an assertion has no
supporting receipt; record `partial` or `unsupported` instead, or narrow the claim.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

from . import registry


def record(c: dict, outcome: str, by: str, when: dt.date) -> None:
    if outcome not in registry.REVIEW_OUTCOMES:
        raise registry.RegistryError(f"outcome must be one of {registry.REVIEW_OUTCOMES}")
    if not by.strip():
        raise registry.RegistryError("--by must name the reviewer")
    bad = registry.integrity_problems(c)
    if bad:
        raise registry.RegistryError(f"{c['id']}: evidence does not match its digest; re-take it with "
                                     f"`drift snapshot --id {c['id']}` and read it first: {'; '.join(bad)}")
    if outcome == "supported":
        probe = {k: v for k, v in c.items() if k not in registry.AUTO_KEYS}
        gaps = [w for w in registry.publishable({**probe, "review_hash": registry.review_hash(c),
                                                  "review_claim_hash": registry.claim_hash(c),
                                                  "review_outcome": "supported"})]
        if gaps:
            raise registry.RegistryError(f"{c['id']}: cannot record 'supported': {'; '.join(gaps)}")
    c["reviewed_at"] = when.isoformat()
    c["reviewed_by"] = by.strip()
    c["review_outcome"] = outcome
    c["review_hash"] = registry.review_hash(c)
    c["review_claim_hash"] = registry.claim_hash(c)
    for k in registry.AUTO_KEYS:  # a person's review supersedes any automated re-check
        c.pop(k, None)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="drift review", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true", help="list review state for every claim; writes nothing")
    g.add_argument("--id", action="append", help="claim id to record a review for (repeatable)")
    ap.add_argument("--outcome", choices=registry.REVIEW_OUTCOMES)
    ap.add_argument("--by", help="who read the evidence")
    ap.add_argument("--date", help="review date YYYY-MM-DD (default today; never in the future)")
    ap.add_argument("--registry", type=Path, default=registry.REGISTRY)
    args = ap.parse_args(argv)

    try:
        claims = registry.load(args.registry)
        if args.status:
            bad = 0
            for c in claims:
                why = registry.publishable(c)
                bad += bool(why and c.get("on_map", True))
                tag = "on-map" if c.get("on_map", True) else "candidate"
                when, by = registry.last_check(c)
                check = f"{by} {when}" if when else "-"
                print(f"{registry.review_state(c):8} {c.get('review_outcome') or '-':12} {check:17} {c['id']:32} {tag:9} "
                      f"{'; '.join(why) or 'publishable'}")
            print(f"\n{bad} on-map claim(s) cannot publish")
            return 1 if bad else 0
        if not args.outcome or not args.by:
            ap.error("--id needs --outcome and --by")
        today = dt.date.today()
        when = dt.date.fromisoformat(args.date) if args.date else today
        if when > today:
            ap.error("--date cannot be in the future")
        by_id = {c["id"]: c for c in claims}
        for cid in args.id:
            if cid not in by_id:
                raise registry.RegistryError(f"no claim {cid}")
            record(by_id[cid], args.outcome, args.by, when)
            print(f"reviewed {cid}: {args.outcome} by {args.by} on {when}")
        registry.save(claims, args.registry)
        return 0
    except registry.RegistryError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
