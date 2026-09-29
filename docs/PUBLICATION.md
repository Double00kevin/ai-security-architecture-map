# Publication safety

The weekly job only starts from a clean tracked and untracked working tree. Keep unpublished drafts
outside the checkout or in a deliberately ignored local directory. The job refuses to include files
left in `maps/` or `reports/` before the run.

Automatic re-checks require a valid starting chain: either the current evidence still has a valid
supported human review, or a valid previous automatic check carries that review. Refreshing a
snapshot can break both. An unchanged response on the next run cannot repair that chain; a person
must read the new evidence and record a review. Source type, locator, excerpt length and approved
redirect are part of the binding as well as the URL and evidence digest.

## Evidence freshness at review time

A review assesses evidence, so the evidence must be fresh when it is assessed. `drift review` refuses
unless every receipt's `fetched_at` is on the review date or at most `REVIEW_FETCH_MAX_DAYS` (7) days
before it, and never after it (`drift/registry.py`, next to the other policy constants). The fetch
dates are recorded in the review event (`review_fetched_at`), and `publishable` applies the same rule
to every review-based check, so a hand-written record over a 2020 fetch cannot publish or be carried
forward by an automated re-check. Re-taking evidence with `drift snapshot` changes the fetch dates and
therefore always needs a new review, even when the excerpt is unchanged.

Automated re-checks already use fresh evidence: `drift auto` renews a claim only from the excerpts
fetched by the same weekly `drift check` run, and records that run's date as every receipt's
`fetched_at`. There is no evidence policy yet for stable historical facts whose source cannot be
re-fetched; see `DEFERRED.md`.

## Time-based claims (freshness rules)

Some claims are only true while something recent keeps happening. The Qwen claim says the Qwen
organisation's most recently modified model repository "was updated within the last 30 days"; an
unchanged excerpt stops being evidence for that after 30 days. Such a receipt carries a rule:

```yaml
freshness:
  field: lastModified   # the JSON key whose ISO timestamp the excerpt holds
  max_age_days: 30
```

`drift check` flags the receipt (`freshness`) when the timestamp in the fresh excerpt (or the stored
one, if the source could not be fetched) is older than `max_age_days`; triage routes it to the owner
without a model call; `drift auto` refuses to renew the claim and gives the reason in its report.

The rule is deliberately **not** part of the review or claim digest: it is a check setting, not
something the claim says, and binding it would have voided the existing Qwen review, which may only
be re-recorded after the evidence is actually re-read. The consequence is that removing or loosening a
rule does not void a review; that edit is visible only in git history and review.

The 180-day rule limits the age of the human review **when an automatic check is made**. An accepted
check can support a publication for up to 30 more days. It is not a hard 180-day lifetime for the map.

Before publishing a version, the builder prepares its JSON, renders and verifies the PNG and sidecar
in a staging directory. Registry and document updates are prepared there too. It promotes the complete
version and replaces the files only after preparation succeeds. A handled promotion failure restores
the previous files and removes only the newly created version. Render/transport/filesystem failures
are errors (exit 1), not requests for an editorial decision (exit 3).

The weekly script runs both `drift map check` and `drift map verify` before staging. Any failed stage
prevents commit and push, leaving reports available locally. Verification checks:

- Current on-map claims remain publishable and their visible content matches the published version.
- The publication's own version date, review/check dates, oldest dates, 30-day window and expiry are
  internally consistent. Later registry renewals do not change an older publication's dates.
- MAP.md and the README block match the published JSON.
- The committed PNG decodes as PNG, has the expected dimensions and matches the renderer pixel for
  pixel. Its text sidecar must match too.

Multi-file filesystem updates cannot be made crash-atomic with this layout. If the process is killed
or power fails during promotion, the next weekly run stops on its dirty-tree gate. Inspect the local
changes and failure logs, preserve any unrelated work, then repair or discard only the interrupted
run's outputs before retrying. Do not bypass the clean-tree or verification gate. An incomplete
version that was already committed must be repaired through a reviewed change; automatic publication
does not rewrite version history.

The script still uses the existing explicit `HEAD:main` publication route, subject to repository
permissions and protection rules. Moving routine runs to pull requests remains tracked in
`DEFERRED.md`. Tests use only local bare remotes, never the production repository or scheduled task.

## Review-hash migration in this fix

The 73 existing review records were checked against their prior payload and excerpt digests before
expanding the binding to source extraction settings. Only `review_hash` and `review_claim_hash` were
recomputed. No excerpt, claim, source setting, reviewer, review date or outcome was changed. This is
a binding-format migration, not a new factual review, and it does not extend any expiry date.

New schema-3 maps also retain each tool's human-review hash and the hash of the check used. These
hashes are audit references, not signatures. Verifying a historical publication independently of
today's registry still needs the input/artifact manifest tracked in `DEFERRED.md`.
