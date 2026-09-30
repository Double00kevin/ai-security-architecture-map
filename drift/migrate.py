"""`drift migrate review-events`: the one-time migration that binds existing review records into a
review-event digest (2026-09-29 audit, A03).

    python -m drift migrate review-events            # rewrite registry/claims.yaml
    python -m drift migrate review-events --dry-run  # report only

Before this migration a review record was five fields (reviewed_at, reviewed_by, review_outcome,
review_hash, review_claim_hash) and only the two hashes were bound to anything: the outcome, the
assessor, the review date and the receipts' fetch dates could be edited without voiding the review.

For every claim with a review record in that old format, this adds
- `review_fetched_at`: each receipt's fetched_at as it stands, and
- `review_event_hash`: the digest of the event (see registry.review_event_payload).

It takes no date or reviewer as input and changes no existing field: no date, outcome, reviewer,
hash, claim or evidence. So it cannot make a review younger or restore a review that was void.
It refuses, and writes nothing, when any old-format review is not currently valid (evidence digest,
claim/evidence hash or claim hash no longer match), and when the registry has already been migrated.
This is a binding-format change, not a new review.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from . import registry

OLD_KEYS = ("reviewed_at", "reviewed_by", "review_outcome", "review_hash", "review_claim_hash")
NEW_KEYS = ("review_fetched_at", "review_event_hash")


def add_review_events(claims: list[dict]) -> int:
    """Add the event binding to every old-format review record in place. Returns how many were bound.
    All or nothing: raises RegistryError, having changed nothing, if any record cannot be bound."""
    todo, problems = [], []
    for c in claims:
        has_old = [k for k in OLD_KEYS if c.get(k) not in (None, "")]
        has_new = [k for k in NEW_KEYS if c.get(k) not in (None, "")]
        if has_new:
            problems.append(f"{c.get('id')}: already has {has_new} (registry already migrated?)")
            continue
        if not has_old:
            continue
        if len(has_old) != len(OLD_KEYS):
            problems.append(f"{c['id']}: incomplete review record {has_old}")
        elif registry.integrity_problems(c):
            problems.append(f"{c['id']}: evidence does not match its digest")
        elif c["review_hash"] != registry.review_hash(c) or c["review_claim_hash"] != registry.claim_hash(c):
            problems.append(f"{c['id']}: review no longer matches the claim/evidence; it needs a new review, not a migration")
        elif any(k in c for k in registry.AUTO_KEYS + registry.APPROVAL_KEYS):
            problems.append(f"{c['id']}: carries automated-check or approval fields that predate the migration")
        else:
            todo.append(c)
    if problems:
        raise registry.RegistryError("review-event migration refused, nothing written:\n  - " + "\n  - ".join(problems))
    for c in todo:
        c["review_fetched_at"] = registry.fetch_dates(c)
        c["review_event_hash"] = registry.review_event_hash(c)
    return len(todo)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="drift migrate", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("migration", choices=["review-events"])
    ap.add_argument("--registry", type=Path, default=registry.REGISTRY)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    with Path(args.registry).open("r", encoding="utf-8") as f:
        claims = yaml.safe_load(f)["claims"]  # not registry.load: old-format records do not validate any more
    try:
        n = add_review_events(claims)
        if not args.dry_run:
            registry.save(claims, args.registry)
    except registry.RegistryError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"{'would bind' if args.dry_run else 'bound'} {n} review record(s) into a review-event digest; "
          "no date, outcome, reviewer, claim or evidence changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
