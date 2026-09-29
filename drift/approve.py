"""`drift approve`: record the owner's approval of review events, from a merged pull request.

    python -m drift approve --pr 12             # after PR 12 is merged, on an up-to-date main
    python -m drift approve --pr 12 --dry-run   # show what would be stamped; write nothing

A review event (`drift review`) is an AI assessment of primary-source evidence. The owner approves it
by merging the pull request that adds or changes it. This command turns that merge into a verifiable
record on each claim:

    approved_by: Double00kevin     # registry.OWNER_LOGIN, never a command-line argument
    approved_at: '2026-10-02'      # the PR's merged_at date
    approval_ref: https://github.com/Double00kevin/ai-security-architecture-map/pull/12

The three fields are part of the review event digest, so editing any of them, or the review they
approve, voids the event. It refuses, and writes nothing, unless all of these hold:

- the GitHub REST API says the PR is merged into `main` of registry.REPOSITORY, and
  `merged_by.login` is registry.OWNER_LOGIN;
- the merge commit is in the local clone (run `git fetch origin main` first);
- the PR changed at least one review event: registry/claims.yaml is compared between the merge
  commit's first parent (the base the PR was merged into) and the merge commit, and only claims
  whose review event was added or changed there are stamped;
- each of those claims still carries exactly that review event in the working registry, has an
  intact event digest, and has no approval yet.

It reads GITHUB_TOKEN from the environment if set (the repository is public, so it is optional) and
never prints it. Run it after the merge, on `main`; the owner commits the result to `main`. It never
runs in the weekly job, and nothing else writes the approval fields.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import yaml

from . import registry

API = "https://api.github.com/repos/{repo}/pulls/{number}"
TIMEOUT_S = 20
MAX_BYTES = 2 * 1024 * 1024


class ApprovalError(Exception):
    pass


def fetch_pr(number: int) -> dict:
    """GET the pull request from the GitHub REST API (HTTPS, fixed host, timeout, size cap)."""
    req = urllib.request.Request(API.format(repo=registry.REPOSITORY, number=number), headers={
        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ai-security-architecture-map-approve"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        req.add_unredirected_header("Authorization", f"Bearer {token}")  # never sent on to a redirect target
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            body = resp.read(MAX_BYTES + 1)
    except OSError as e:  # URLError/HTTPError are OSErrors; the message never contains the token
        raise ApprovalError(f"GitHub API request for PR {number} failed: {type(e).__name__}: {str(e)[:200]}") from None
    if len(body) > MAX_BYTES:
        raise ApprovalError("GitHub API response too large")
    pr = json.loads(body.decode("utf-8"))
    if not isinstance(pr, dict):
        raise ApprovalError("GitHub API response is not a pull request object")
    return pr


def _git_show(repo_dir: Path, rev: str, path: str) -> str:
    r = subprocess.run(["git", "-C", str(repo_dir), "show", f"{rev}:{path}"], capture_output=True,
                       text=True, encoding="utf-8")
    if r.returncode != 0:
        raise ApprovalError(f"cannot read {path} at {rev[:12]}: is the merge commit fetched? (git fetch origin main)")
    return r.stdout


def _claims_at(repo_dir: Path, rev: str) -> dict[str, dict]:
    data = yaml.safe_load(_git_show(repo_dir, rev, "registry/claims.yaml")) or {}
    return {c["id"]: c for c in data.get("claims") or []}


def _event(c: dict | None) -> tuple | None:
    if not c or not c.get("review_event_hash"):
        return None
    return tuple(json.dumps(c.get(k), sort_keys=True, default=str) for k in registry.REVIEW_KEYS)


def check_pr(pr: dict, number: int) -> None:
    problems = []
    if pr.get("number") != number:
        problems.append(f"API returned PR {pr.get('number')!r}, not {number}")
    if pr.get("merged") is not True:
        problems.append("PR is not merged")
    if ((pr.get("merged_by") or {}).get("login")) != registry.OWNER_LOGIN:
        problems.append(f"PR was merged by {((pr.get('merged_by') or {}).get('login'))!r}, not {registry.OWNER_LOGIN}")
    base = pr.get("base") or {}
    if base.get("ref") != "main" or ((base.get("repo") or {}).get("full_name")) != registry.REPOSITORY:
        problems.append(f"PR base is not main of {registry.REPOSITORY}")
    if pr.get("html_url") != f"https://github.com/{registry.REPOSITORY}/pull/{number}":
        problems.append("PR html_url does not match this repository")
    if not pr.get("merge_commit_sha") or not pr.get("merged_at"):
        problems.append("PR has no merge commit or merge date")
    if problems:
        raise ApprovalError("approval refused:\n  - " + "\n  - ".join(problems))


def approvals(pr: dict, number: int, claims: list[dict], repo_dir: Path) -> list[str]:
    """Stamp the approval on every claim whose review event the PR added or changed. All or nothing."""
    check_pr(pr, number)
    merge = pr["merge_commit_sha"]
    before, after = _claims_at(repo_dir, f"{merge}^1"), _claims_at(repo_dir, merge)
    changed = sorted(cid for cid, c in after.items() if _event(c) and _event(c) != _event(before.get(cid)))
    if not changed:
        raise ApprovalError(f"PR {number} added or changed no review event in registry/claims.yaml; nothing to approve")
    when = dt.date.fromisoformat(str(pr["merged_at"])[:10])
    by_id = {c["id"]: c for c in claims}
    problems = []
    for cid in changed:
        c = by_id.get(cid)
        if c is None:
            problems.append(f"{cid}: no longer in the registry")
        elif any(c.get(k) not in (None, "") for k in registry.APPROVAL_KEYS):
            problems.append(f"{cid}: already approved ({c.get('approval_ref')})")
        elif _event(c) != _event(after[cid]):
            problems.append(f"{cid}: its review event changed after PR {number} was merged")
        elif not registry.review_event_intact(c):
            problems.append(f"{cid}: review event digest is not intact")
        elif when < registry._date(c["reviewed_at"]):
            problems.append(f"{cid}: merged {when}, before its review on {c['reviewed_at']}")
    if problems:
        raise ApprovalError("approval refused, nothing written:\n  - " + "\n  - ".join(problems))
    for cid in changed:
        c = by_id[cid]
        c.update(approved_by=registry.OWNER_LOGIN, approved_at=when.isoformat(), approval_ref=pr["html_url"])
        c["review_event_hash"] = registry.review_event_hash(c)
    return changed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="drift approve", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pr", type=int, required=True, help="number of the merged pull request")
    ap.add_argument("--registry", type=Path, default=registry.REGISTRY)
    ap.add_argument("--repo-dir", type=Path, default=registry.ROOT, help=argparse.SUPPRESS)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    try:
        claims = registry.load(args.registry)
        stamped = approvals(fetch_pr(args.pr), args.pr, claims, args.repo_dir)
        if not args.dry_run:
            registry.save(claims, args.registry)
    except (ApprovalError, registry.RegistryError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    for cid in stamped:
        print(f"{'would approve' if args.dry_run else 'approved'} {cid}: PR {args.pr} merged by {registry.OWNER_LOGIN}")
    print(f"{len(stamped)} review event(s) {'would be ' if args.dry_run else ''}marked owner-approved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
