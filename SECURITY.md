# Security

This repository is run by one person (@00Kevin) as a public, receipts-first record of the AI architecture map. It is a security-themed project, so it tries to hold itself to the controls on its own map.

## Reporting a problem

Please report security issues privately rather than in a public issue:

- GitHub: use **Report a vulnerability** on this repository's Security tab (private vulnerability reporting), or
- X: DM @00Kevin.

Include what you found, how to reproduce it, and what you think the impact is. You will get a reply within 7 days. Fixes are published as ordinary commits; credit is given in the changelog unless you ask otherwise.

In scope: anything in this repository (the checkers, the renderer, the workflow files, the registry data) and the way it fetches or processes third-party content. Out of scope: vulnerabilities in the tools the map lists; report those to their vendors.

## How this repo protects itself

- **Secrets never enter git.** `.env` is gitignored, a gitleaks pre-commit hook has run since the first commit, and CI scans the full history on every push. The only secret the project uses is a Claude API key for triage; it lives in `.env` on the machine that runs the weekly job. The GitHub adapter makes unauthenticated calls and reads no token. CI runs the pinned, checksum-verified gitleaks CLI over every commit of the full clone.
- **Fetched content is untrusted input** (layer 07 of the map). The checker fetches only URLs already in `registry/claims.yaml`, HTTPS only, and checks every redirect hop against the registry before following it (at most 3 hops, each to the claim's one approved `redirect_to`), with a 20-second end-to-end deadline and an 8 MB cap, no JavaScript, no cookies, a polite user agent, weekly cadence. Vendor text reaches Claude only as data inside a fixed prompt, with the reply forced through one strict JSON-schema classification tool with no side effects; the model cannot edit the registry or run anything. A heuristic filter routes text that looks like instructions to the owner without sending it; the heuristic will miss things, and the containment is that the model has no tools with side effects and the owner decides on every flagged change.
- **Triage never writes.** Claude classifies diffs. Claim edits and review events arrive through pull requests; a review (`drift review`) is an AI assessment whose `reviewed_by` names the assessor, bound by hash to the exact claim, owner, evidence, outcome, assessor and dates. The owner's approval is recorded only from a pull request the owner merged (`drift approve`).
- **Dependencies are pinned with hashes** (`requirements.txt`, `requirements-dev.txt` from pip-compile), GitHub Actions are pinned to commit SHAs, and Dependabot proposes updates to a named owner (layer 01 of the map).
- **No infrastructure details** (hostnames, addresses, usernames, local paths) are kept in code, logs, reports or docs.
- **Snapshots are short excerpts plus a SHA-256**, not copies of vendor pages.

## Supported versions

Only the current `main` branch and the newest map version tag are maintained. Map versions expire 30 days after their date by design.
