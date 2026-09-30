# Contributing

Thanks for poking holes in it. Two kinds of contribution are most useful.

## 1. A claim is stale or wrong

Open an issue with the **"Claim is stale"** template. It requires a link to a primary source: the vendor's own docs, changelog, blog or press release, the official GitHub organisation, or the package registry. Aggregators, "top tools" lists and AI answers are leads, not proof, and will be treated as such.

What happens next: the claim is re-checked against your source, `registry/claims.yaml` is updated in a pull request (never by the AI triage step), a new evidence snapshot is taken, an AI assessor (Claude) reads it and a review is recorded (`python -m drift review`), the owner decides by merging the pull request, `python -m drift approve` records that approval, and the change ships in the next map version with credit in `CHANGELOG.md`.

## 2. Code

Checkers, tests, renderer fixes and new source types are welcome. Ground rules:

- Python 3.11+, standard library first. A new dependency must remove real code, and it gets pinned with hashes: edit `requirements.in`, then run `uv pip compile --universal --generate-hashes --python-version 3.11 -o requirements.txt requirements.in` (universal, so Windows-only deps such as colorama are kept with their markers).
- Everything must run on Windows 11 and Linux. Use `pathlib`, open files with explicit UTF-8, no bash-only steps in the check path.
- Tests live in `tests/` and never touch the network (see `tests/conftest.py` for the in-memory HTTP fake). Fixtures never contain real secrets; build fake tokens at runtime.
- The fetcher's rules are not negotiable: HTTPS only, registry URLs only, timeout and size caps. Do not add scraping, JavaScript execution or crawling.
- Every string that appears on the rendered map must come from `map.json`; `tests/test_render.py` enforces this.
- Install the hook before your first commit: `git config core.hooksPath .githooks` (needs gitleaks on PATH). Never commit with `--no-verify`.

Run before opening a pull request:

```bash
python -m pip install --require-hashes -r requirements.txt -r requirements-dev.txt
python -m pytest
python -m drift map check
python -m drift map verify
```

CI runs the same on Ubuntu and Windows with Python 3.11 and 3.13, plus the gitleaks CLI over the full history.

## What is not accepted

- Adding tools to the map without a receipt. Add them as candidates (`on_map: false`) with a verified source; the owner curates the map itself.
- Changes to the 12 security controls or the map copy. Those are the owner's editorial content; open a discussion instead.
- Anything that stores full copies of vendor pages, sends fetched text to a model without the fixed prompt and schema, or writes to the registry automatically.

## Licence of contributions

By contributing you agree that code is licensed under the repository's code licence and map content under its content licence (see `LICENSE`).
