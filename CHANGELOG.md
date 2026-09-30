# Changelog

## v2026.09.29.1 (accurate review labels; 2026-09-29 audit fixes)

Same tools, controls, evidence and review dates as v2026.09.29; it expires on the same date
(2026-10-28). This re-issue exists because the labels and the poster wording changed.

- **Provenance correction.** Versions v2026.09.27.1 through v2026.09.29 labelled checks "person"
  (`map.json`) and "human review" (MAP.md), and the README described reviews as a person's. Every
  review record behind those versions was AI-assessed: `reviewed_by` is `claude` or `claude-code` on
  all 73 records. No person reviewed the evidence and no owner approval was recorded. The labels are
  corrected from this version on. The published files of the earlier versions are not edited.
- Checks are now called what they are: an **AI-assessed review** (`drift review`; `reviewed_by`
  names the assessor), an **automated re-check** (`drift auto`, a deterministic rule), and
  **owner-approved** only where `drift approve` recorded an approval from a pull request the owner
  merged. None of the current reviews is owner-approved; none was backfilled.
- `map.json` schema 4: `checked_by` is `review` or `auto`, and each tool carries `reviewed_by` and its
  owner-approval state. The newest map must be the current schema; the four earlier versions are
  pinned by digest as legacy.
- Review events now bind outcome, assessor, review date, every receipt's fetch date and any approval
  (`review_event_hash`); the 73 existing records were migrated without changing any date, outcome or
  reviewer. A review must rest on evidence fetched at most 7 days before it.
- The Qwen claim ("updated within the last 30 days") has a freshness rule: once the observed
  timestamp is older than 30 days it is flagged and not renewed automatically.
- Poster: the subtitle now reads "12 capability areas an AI build can draw on, example tools for
  each, and one security control to start with." (was "12 layers every AI build runs on, the tools
  for each, and the security control none of them should ship without."), and a scope line reads
  "Illustrative. Not an endorsement or a complete security baseline. A starting point, not a finish
  line." The video hook reads "An AI build can touch up to 12 layers. Every one you use is an attack
  surface." Wording approved by the owner.
- Media: map.png. Videos are rendered on demand for posts.

## v2026.09.29 (new repository name; publication integrity)

- The repository is now `Double00kevin/ai-security-architecture-map`, published fresh with a single
  commit. Tool list, controls, evidence and reviews are unchanged from v2026.09.28; this version
  exists so the map image prints the new repository address. It expires on the same date.
- Automatic renewal now requires a valid starting review chain. Refreshing changed evidence cannot
  silently restore an invalidated human review. Fresh evidence digests are checked even for reports
  labelled unchanged; duplicate receipt findings are refused.
- Review bindings now include source type, locator, excerpt length and approved redirect. Migrated
  only the two hashes of all 73 previously valid review records; preserved evidence, claims, reviewers,
  dates and outcomes. This does not represent a new review or renew the current map.
- Map generation renders and verifies in staging before promotion, restores prior registry/documents
  on handled promotion errors, and reports renderer failures as errors. The weekly job verifies the
  final artifacts and never commits or pushes after a failed stage.
- Publication checks independently validate serialized dates/expiry and compare decoded PNG pixels,
  dimensions and sidecars. New schema-3 maps retain review/check hashes for audit reference.
- Pre-existing untracked drafts now block the weekly job. Added regression coverage for broken review
  chains, failed renders and document promotion, altered dates, corrupt/wrong images and unintended
  publication, including Windows PowerShell 5.1 and PowerShell 7 local-origin tests.
- Published v2026.09.28 media and its expiry remain unchanged. Recovery limitations and the existing
  direct-to-main publishing route are documented in `docs/PUBLICATION.md`.

Map versions are calendar versions, year first (`vYYYY.MM.DD`, `vYYYY.MM.DD.N` for a same-day re-issue), and are git tags on this repo. The public history of this repository starts at `v2026.09.29`; earlier versions below are kept in `maps/` but have no tags here. A version is trusted until the earlier of 30 days from its date and 30 days from the oldest check behind it (a person's review, or an automated re-check of a routine change that carries a person's review forward for up to 180 days). Versions marked "(automatic)" were published by the weekly job. The 12 security controls are versioned here too but are not drift-checked.

## v2026.09.28 (audit remediation)

An external audit of `v2026.09.27.1` (2026-09-28) and a second review of the fix found real defects. What was wrong, and what changed:

- **A map could be built from old or missing evidence.** Its 30-day trust window came from the version string, so evidence from 2020 got a fresh window; a map dated 2099 passed; a claim with no excerpt, a layer 99 and a duplicated tool were accepted. Now every tool on the map carries a review of its evidence, bound by a hash to the claim text, owner, receipts and excerpts. Every excerpt's sha256 is recomputed on load. A map is built only from supported, valid reviews, expires 30 days after its oldest review, and is refused if it would already be expired. `drift map verify` (CI) fails when a published claim loses its review or the registry no longer reproduces the committed map.
- **Redirects could take the fetcher outside the registry, and the 20 s deadline was per socket read.** Every redirect hop must be the claim's one approved destination (max 3), and the deadline now holds against a server that trickles bytes and against a connect or header that hangs.
- **Receipts that did not prove their claims.** Claims now list what they assert (capability, availability, ownership, lifecycle) and each receipt what it supports; many claims were narrowed to what their sources say. Replaced or supplemented: Llama, Llama Guard, Gemini, Check Point AI Guardrails, Voyage, Make, LlamaParse, Zep, Mistral, Pinecone.
- **Ownership events were missed.** Langfuse: acquired by ClickHouse (vendor post dated 2026-01-16). Promptfoo: agreed to be acquired by OpenAI (2026-03-09), closing not verified. Voyage: acquired by MongoDB (announced 2025-02-24). `status` now means lifecycle only; ownership has its own fields, so an acquired product that is still offered stays `active`.
- **Unresolved reviews looked clean.** An unsupported or partial review is now flagged every week until fixed, and triage cannot clear it.
- **Triage undercounted spend and aborted on network errors.** Every attempt is counted before it is sent, the worst-case cost is reserved against the cap, and failures are recorded per finding.
- **The weekly job on Windows could report success without running.** A helper named `Tee` lost to PowerShell's built-in `tee` alias, so on Windows PowerShell no pipeline bound, no log was written, and the run could record every stage as ok. Helpers are renamed and checked at start, every native command must produce an exit code, the check must write a report, and CI runs the whole script under Windows PowerShell 5.1.
- **Media freshness.** The video footer ran off the frame; the PNG carried no version at all. Both now show the version, oldest review and review-due date (the PNG also the repo), and tests check that text is visible, inside the frame and not overlapping.
- **Docs that overstated.** The layers are described as capability areas, not a strict pipeline; the governance footer "names the frameworks the controls draw on"; CI now really scans the full history with a checksum-verified gitleaks CLI.
- Tools: unchanged (69; per layer 10, 5, 6, 5, 5, 7, 5, 5, 5, 6, 5, 5). Controls: unchanged. Candidates: Helicone, Letta, Guardrails AI, Ragas (Helicone's review is partial and flagged).
- Media rendered from `map.json`: `map.png`, `map.mp4`, `map-vertical.mp4`. Oldest review 2026-09-28; review due 2026-10-28.
- Still open, with closure criteria in `DEFERRED.md`: an adversarial corpus for the injection heuristic, a per-version artifact manifest, publishing weekly reports through a pull request with a required CI check, fetch retries with backoff, lint and coverage in CI.

## v2026.09.27.1 (map v2)

Same-day re-issue with the first content change since the 2026-09-26 map.

- Tools: 62 → 69. Added Bedrock, Kong, Microsoft Agent Framework, Airbyte, BGE, Llama and Mistral, all verified against primary sources. Per layer: 10, 5, 6, 5, 5, 7, 5, 5, 5, 6, 5, 5.
- Verified but not on the map: Helicone (acquired by Mintlify 2026-03-03; service in maintenance mode), Letta, Guardrails AI, Ragas. They stay in the registry as candidates (`on_map: false`) with receipts.
- Controls: layer 01 now reads "pinned versions with a named owner" (suggested publicly by @tonytonggg). Other control wording tightened.
- New: "Govern it all" footer carried in `registry/governance.yaml` (OWASP LLM Top 10 2026, OWASP Agentic Top 10, NIST AI RMF, ISO/IEC 42001, MITRE ATLAS).
- Media rendered from `map.json`: `map.png` (2160x2700), `map.mp4` (1080x1350, 40.8 s), `map-vertical.mp4` (1080x1920, 40.8 s). Every string on every frame comes from the data; see the `.txt` sidecars.
- Expires 2026-10-27.

## v2026.09.27

First registry-backed version. Not tagged: the public history starts at `v2026.09.27.1`.

- Registry seeded with the 62 tools of the 2026-09-26 map (12 layers; 7, 4, 5, 5, 4, 6, 5, 5, 5, 6, 5, 5 per layer).
- Every claim re-verified against a primary source on 2026-09-27: source URL, excerpt, sha256 and date recorded in `registry/claims.yaml`. 62 verified, 0 unverified.
- Map content: unchanged from 2026-09-26. No tool was renamed, acquired, deprecated, killed or found miscategorised since that date.
- Statuses recorded: 59 active, 3 acquired (Prisma AIRS (Portkey), Check Point AI Guardrails, Voyage). All three predate the map and are already reflected in its labels.
- Watch list (no map change): Arcade's package renamed `arcade-ai` → `arcade-mcp`; LlamaParse's SDK moved to `llama-cloud` and its docs now say "Parse"; LlamaFirewall's PyPI package has not shipped since 2025-05-29 although the repo is active. Details: `reports/2026-09-27-seed-verification.md`.
- Controls: unchanged.
- Tooling: `drift/fetch.py` (constrained fetcher) and `drift/snapshot.py` (evidence snapshots).
- 11 further tools verified and recorded as candidates (`on_map: false`) for the next content version.
- `maps/v2026.09.27/map.json` generated from the registry. Expires 2026-10-27.
