# Deferred work from the 2026-09-28 audit

Findings accepted but not closed by the remediation branch. Each entry says what is left and what
would count as closed. No GitHub issues were opened for these; the owner decides what is public.

## F10: adversarial corpus for the injection filter

- Done: README and `drift/triage.py` say the filter is a heuristic and the containment is that the
  model has no side-effecting tools and a human reviews; vendor text is Markdown-escaped in reports.
- Left: a corpus of injection-shaped vendor text (paraphrases, other languages, Unicode confusables,
  zero-width characters, instructions split across the before/after excerpts, instructions inside
  version strings) with a measured miss rate for `INJECTION_RE`, and the same corpus replayed against
  the model with the fixed prompt to measure how often a "noise" verdict survives.
- Closed when: `tests/fixtures/injection-corpus/` exists with at least 50 labelled cases, a test reports
  the filter's recall on it, and the README states the measured number instead of only "heuristic".

## F12: manifest of generated artifacts

- Done: `write_map` refuses to overwrite a published version; same-day re-issues use `vYYYY.MM.DD.N`;
  `drift map verify` (in CI and before weekly publication) checks current claim eligibility and visible
  content, validates the publication's own dates, and compares MAP.md, the README block, decoded PNG
  pixels and the PNG sidecar with the published JSON. New schema-3 maps retain review/check hashes
  as audit references; these are not a complete historical evidence manifest. v2026.09.28 is the first version it checks; the legacy
  v2026.09.27.1 map is schema 1 and is not reproducible from today's registry.
- Left: a per-version manifest (`maps/<version>/MANIFEST.json`) recording the sha256 of every input
  (claims.yaml, controls.yaml, governance.yaml, copy.yaml, fonts, renderer source) and output (map.json,
  map.png, both MP4s, sidecars), so a published version can be verified without today's registry, and
  the legacy v2026.09.27.1 map (schema 1, skipped by `verify`) can be pinned.
- Closed when: `drift map build` writes the manifest, `drift map verify --version <v>` checks any
  version against it, and CI runs it for the newest version.

## F17: publication through a branch and a required status check

- Done: the weekly job refuses to run off `main`, when `main` is ahead of `origin/main`, or on a dirty
  tracked or untracked tree; it verifies publication artifacts and stops before commit/push if any stage
  failed. It pushes with an explicit `HEAD:main` refspec and reports publication as its own status.
- Left: publish weekly reports to a `reports/` branch and open a pull request instead of pushing to
  `main`; make the `ci` workflow (tests, map check, map verify, gitleaks) a required status check on
  `main` with branch protection.
- Closed when: the weekly job no longer pushes to `main`, and the repository settings show `main`
  protected with the CI checks required. (Repository settings are the owner's call; nothing here
  changes them.)

## F19: retry with backoff in the fetcher

- Done: one monotonic 20 s end-to-end deadline per fetch, chunked reads under the 8 MB cap, redirect
  hops checked and capped at 3.
- Left: bounded retry with exponential backoff and jitter for transient failures (connection reset,
  HTTP 429/502/503/504, honouring `Retry-After` up to a cap), with the whole retry sequence still inside
  a per-claim budget, so one flaky vendor does not become a weekly "could not verify".
- Closed when: `drift/fetch.py` retries at most N times within a per-claim budget, never retries on
  4xx other than 429, and tests with a fake clock prove the schedule and the budget.

## F22: control-to-framework mapping (closed by narrowing the claim)

- The finding: the README said the controls "map onto" the listed frameworks, but the repo has no
  control-to-requirement mapping to support that.
- Done: the README now says the footer "names the frameworks the controls draw on", which is what the
  repo supports; governance entries carry a review date and a review-due date.
- Not planned: a full control matrix (scope, threat, enforcement point, owner, test, evidence). The
  audit listed it as optional; it is a different project from a drift-checked map.
- Closed when: no public text claims a mapping the repo does not contain. Met by the wording change;
  reopen if a mapping claim is added.

## F26: lint and coverage in CI

- Done: regression tests for every fixed behaviour; a global no-network guard in `tests/conftest.py`;
  CI stays on Python 3.11 and 3.13 on Ubuntu and Windows.
- Left: a linter (for example ruff, pinned with hashes in `requirements-dev.txt`) and a coverage floor
  (for example coverage.py with `fail_under`) in CI. Adding either is a new dev dependency, which the
  remediation brief did not allow.
- Closed when: CI runs the linter and coverage with a stated floor, and both pass on `main`.
