# Deferred work

Findings accepted but not closed. Each entry says what is left and what would count as closed. No
GitHub issues were opened for these; the owner decides what is public. Entries from the 2026-09-28
audit are marked F.., entries from the 2026-09-29 audit A..; where the two overlap, both ids are given.

## Deferred from the 2026-09-29 audit

The 2026-09-29 audit fixes closed A01 (labels and owner approval), A02 (schema), A03 (review-event
digest), A04 (fetch window), A05 (freshness rules) and A17 (poster wording), and added detection for
A07/A10. A06, A09, A15 and A16 are the F-entries below. Scope and closure criteria for A08, A11-A14
and A18 are taken from the audit as supplied by the owner.

### A07: weekly job in a disposable checkout

- Done (detection only): a failed weekly stage opens a `weekly-run-failed` GitHub issue from
  `scripts/weekly-check.ps1`; the Monday CI `watch` job fails when the published map is closer to
  expiry than a healthy Saturday run allows, or a governance review is due within 7 days.
- Left: run the weekly job from a fresh, disposable checkout instead of the long-lived working tree,
  so an interrupted run cannot leave state for the next one.
- Closed when: the scheduled job creates and removes its own checkout per run, and the harness
  proves an interrupted run leaves nothing behind.

### A08: optional AI triage can block deterministic publication

- Scope: a nonzero `drift triage` result marks the stage failed, and the publish gate then blocks all
  publication; the wrapper runs triage only when `.env` exists.
- Closed when: the owner decides whether triage is advisory or mandatory. If advisory, a triage
  failure stays visible but does not block otherwise-eligible deterministic publication; an
  environment-injected key is supported; tests cover an API outage and a budget stop; the README
  states the policy.

### A11: receipt extraction can miss material changes outside the excerpt

- Scope: an excerpt can omit what matters (per the audit, the Helicone excerpt misses the Mintlify
  acquisition sentence, and the Claude excerpt is truncated before the model lineup).
- Closed when: receipts are assertion-specific with enough context; a lifecycle or ownership change
  outside an old excerpt can trigger a review in a fixture test; irrelevant internal API deprecations
  do not imply product death.

### A12: the URL allowlist does not exclude non-public destinations

- Scope: private, loopback and link-local destinations are not excluded, and resolved addresses are
  not validated.
- Closed when: non-public destinations and resolution changes are denied before connecting (tests
  with mocked resolution), redirects are handled the same way, and public sources still work.

### A13: registry writes and builds are not atomic or locked

- Scope: `registry.save` truncates in place; a manual `drift map build` lacks the staged
  render-and-promote path `drift auto` uses; there is no publication lock.
- Closed when: the registry is written to a temp file, validated and atomically replaced; manual and
  automatic builds share one lock and one staged path; an interrupted write leaves the prior registry
  intact; concurrent runs fail cleanly.

### A14: YAML loading is not strict

- Scope: duplicate keys are not rejected and there is no strict schema, so unknown fields and wrong
  types survive loading.
- Closed when: duplicate keys, typoed security-relevant fields, malformed lists and contradictory
  dates fail clearly before any mutation or publication, for claims, controls, copy and governance,
  using only the standard library and PyYAML.

### A18: Quickstart and scheduler setup

- Scope: the Quickstart is one Bash block mixing read-only and mutating steps with no isolated
  environment; the Windows scheduled task depends on PATH.
- Closed when: read-only setup is separate from maintainer procedures; PowerShell and Bash variants
  use explicit interpreters and a venv; a clean checkout can run a read-only check without a model
  key; the docs say how the operator finds the last successful scheduled run.

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
- Left (A15): deterministic signals (stale, lifecycle, unresolved review, integrity, freshness, error)
  must survive every possible model output, and no model output may change what is published.
- Closed when:
  - a labelled corpus in `tests/fixtures/injection-corpus/` covers the cases above, and a test reports
    the filter's recall on it; the README states the measured number instead of only "heuristic";
  - model misclassification is measured separately from the regex recall, by replaying the corpus
    against the fixed prompt, and reported on its own;
  - tests prove that every model verdict, including malformed or adversarial ones, leaves the
    deterministic flags set and changes nothing in the registry, the map or the publication path.

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
- Left (A09): published versions, their tags, and any release assets are not protected against being
  moved, deleted or replaced.
- Closed when: the weekly job no longer pushes to `main`; the repository settings show `main` protected
  with the CI checks required; and version tags, releases and their assets are immutable (tag
  protection or rulesets that forbid moving or deleting `v*` tags, and releases whose assets cannot be
  replaced). (Repository settings are the owner's call; nothing here changes them.)

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
- Left (A16): dependency maintenance. There is no advisory check on the pinned dependencies, and the
  lock refresh (`uv pip compile --universal --generate-hashes`) is not a documented, tested procedure.
- Closed when: CI runs the linter and coverage with a stated floor, and both pass on `main`; dependency
  advisories are checked (repository advisory alerts enabled by the owner, or an advisory scan of the
  pinned lockfiles in CI that fails on known vulnerabilities); and an owner-driven lock refresh
  procedure is documented and tested (regenerate both lockfiles with hashes, install with
  `--require-hashes`, run the full suite) before its result is merged.
