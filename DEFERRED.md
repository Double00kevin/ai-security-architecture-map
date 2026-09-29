# Deferred work

Findings accepted but not closed. Each entry says what is left and what would count as closed. No
GitHub issues were opened for these; the owner decides what is public. Entries from the 2026-09-28
audit are marked F.., entries from the 2026-09-29 audit A..; where the two overlap, both ids are given.

## Deferred from the 2026-09-29 audit

The 2026-09-29 audit fixes closed A01 (labels and owner approval), A02 (schema), A03 (review-event
digest), A04 (fetch window), A05 (freshness rules) and A17 (poster wording), and added detection for
A07/A10. The audit report itself is not in this repository; A06, A09, A15 and A16 are the F-entries
below. For A11, A12, A13, A14 and A18 the scope and closure criteria still have to be copied from the
audit report by the owner; nothing here should be read as a summary of them.

### A07: weekly job in a disposable checkout

- Done (detection only): a failed weekly stage opens a `weekly-run-failed` GitHub issue from
  `scripts/weekly-check.ps1`; the Monday CI `watch` job fails when the published map is closer to
  expiry than a healthy Saturday run allows, or a governance review is due within 7 days.
- Left: run the weekly job from a fresh, disposable checkout instead of the long-lived working tree,
  so an interrupted run cannot leave state for the next one.
- Closed when: the scheduled job creates and removes its own checkout per run, and the harness
  proves an interrupted run leaves nothing behind.

### A08: advisory triage

- Left: as described in the audit report (not in this repository).
- Closed when: the audit's closure criteria are copied here and met.

### A11, A12, A13, A14, A18

- Left: as described in the audit report (not in this repository). Not started.
- Closed when: each finding's scope and closure criteria are copied here from the audit and met.

### Evidence policy for stable historical facts (from A04)

- Done: a review needs every receipt fetched on the review date or at most 7 days before it.
- Left: some facts do not change and may stop being fetchable (an acquisition announcement that is
  later taken down). There is no evidence policy for them today; the only route is a fresh fetch.
- Closed when: a documented policy says which claims may rest on an archived excerpt, how that
  excerpt is preserved and verified, and `publishable` enforces it. Until then, no fake fresh fetch.

### Freshness rules are not bound by a digest (from A05)

- Done: `freshness` rules are checked by `drift check` and `drift auto`.
- Left: the rule is excluded from the review and claim digests so adding it did not void a review;
  removing or loosening a rule is therefore visible only in git history.
- Closed when: the next review event of a claim with a rule binds the rule (a new, versioned field in
  the event digest), without re-recording any existing review.

### Renaming the Windows scheduled task

- Left: the task registered as `ai-architecture-map weekly drift check` predates the repository
  rename. Scheduled tasks are the owner's to change.
- Closed when: the owner re-registers the task under the new name and the example in
  `scripts/weekly-check.ps1` uses it.

## From the 2026-09-28 audit

## F10 / A15: adversarial corpus for the injection filter

- Done: README and `drift/triage.py` say the filter is a heuristic and the containment is that the
  model has no side-effecting tools and the owner decides; vendor text is Markdown-escaped in reports.
- Left: a corpus of injection-shaped vendor text (paraphrases, other languages, Unicode confusables,
  zero-width characters, instructions split across the before/after excerpts, instructions inside
  version strings) with a measured miss rate for `INJECTION_RE`, and the same corpus replayed against
  the model with the fixed prompt to measure how often a "noise" verdict survives.
- Closed when: `tests/fixtures/injection-corpus/` exists with at least 50 labelled cases, a test reports
  the filter's recall on it, and the README states the measured number instead of only "heuristic".

## F12 / A06: manifest of generated artifacts

- Done: `write_map` refuses to overwrite a published version; same-day re-issues use `vYYYY.MM.DD.N`;
  `drift map verify` (in CI and before weekly publication) checks current claim eligibility and visible
  content, validates the publication's own dates, and compares MAP.md, the README block, decoded PNG
  pixels and the PNG sidecar with the published JSON. New schema-3 maps retain review/check hashes
  as audit references; these are not a complete historical evidence manifest. Since the 2026-09-29
  audit fixes the newest version must be the current schema (4); the historical versions
  v2026.09.27 through v2026.09.29 are pinned in `LEGACY_MAPS` by the SHA-256 of their map.json and are
  reported as SKIPPED (not success) if one of them is ever the newest.
- Left: a per-version manifest (`maps/<version>/MANIFEST.json`) recording the sha256 of every input
  (claims.yaml, controls.yaml, governance.yaml, copy.yaml, fonts, renderer source) and output (map.json,
  map.png, both MP4s, sidecars), so a published version can be verified without today's registry, and
  the pinned legacy maps can be verified as far as their inputs allow.
- Closed when: `drift map build` writes the manifest, `drift map verify --version <v>` checks any
  version against it, and CI runs it for the newest version.

## F17 / A09: publication through a branch and a required status check

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

## F26 / A16: lint and coverage in CI

- Done: regression tests for every fixed behaviour; a global no-network guard in `tests/conftest.py`;
  CI stays on Python 3.11 and 3.13 on Ubuntu and Windows.
- Left: a linter (for example ruff, pinned with hashes in `requirements-dev.txt`) and a coverage floor
  (for example coverage.py with `fail_under`) in CI. Adding either is a new dev dependency, which the
  remediation brief did not allow.
- Closed when: CI runs the linter and coverage with a stated floor, and both pass on `main`.
