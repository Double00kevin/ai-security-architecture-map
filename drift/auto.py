"""`drift auto`: the weekly job's publishing step. Renews routine claims, and publishes a new map
version when one is needed, with no person in the loop for routine weeks.

    python -m drift auto --report reports/2026-10-03T130000Z.json   # the check report this run wrote
    python -m drift auto --report ... --dry-run                     # decide and print; write nothing

For every claim, using the fresh evidence already in the check report (nothing is fetched again):

- RENEWED automatically when a person's `supported` review stands behind it (the claim is unchanged
  since that review and the review is at most 180 days old), every receipt was fetched, and each
  receipt is either unchanged or changed only in version numbers and dates on a package/release
  source (PyPI, npm, GitHub releases/tags). The new excerpts are written to the registry and an
  automated re-check record is added (auto_checked_at / auto_check_basis / auto_check_hash).
- LEFT FOR A PERSON otherwise: a changed page section, a lifecycle signal, a source that could not be
  fetched, an unresolved or missing review, evidence that does not match its digest, a claim edited
  since its review, or a review older than 180 days. Nothing about such a claim is changed; its last
  check keeps counting down, and the map stays live until the oldest check is 30 days old.

A new map version is built (map.json, MAP.md, README block, map.png; videos are rendered on demand
for posts) when what a reader would see differs from the published map, or when the published map is
within RENEW_DAYS of its re-check deadline. A version never changes tools or labels on its own:
content changes only come from registry edits a person reviewed.

Writes reports/<run_id>-auto.json and .md. Exit codes: 0 nothing needs a person; 3 something needs
a person (the run itself succeeded); 1 error; 2 the report does not match the registry.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import mapgen, registry, report

EXIT_OK, EXIT_ERROR, EXIT_SETUP, EXIT_NEEDS_PERSON = 0, 1, 2, 3
ROUTINE_SOURCES = frozenset({"pypi", "npm", "github_release", "github_tag"})
ROUTINE_REASONS = frozenset({"version_bump", "section_changed", "stale"})
RENEW_DAYS = 7  # publish a fresh version when the published one is this close to its re-check deadline

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?")
_VERSION = re.compile(r"(?<![\w.])v?\d+(?:\.\d+)+(?:[-+.]?(?:a|b|rc|dev|post|alpha|beta)\.?\d*)*(?![\w.])")


def mask(text: str) -> str:
    """Excerpt with dates and version numbers replaced, so a routine release reads the same."""
    return _VERSION.sub("<version>", _DATE.sub("<date>", text or ""))


class ReportMismatch(Exception):
    pass


class PublicationError(Exception):
    """An operational failure; never an owner decision or a successful partial publication."""


def _load_report(path: Path, registry_path: Path) -> dict:
    rep = json.loads(Path(path).read_text(encoding="utf-8"))
    if "digest" not in rep or report.content_digest(rep) != rep["digest"]:
        raise ReportMismatch(f"{Path(path).name}: not an intact run report (digest missing or wrong)")
    if rep.get("scope") != "all":
        raise ReportMismatch(f"{Path(path).name}: scope {rep.get('scope')!r}; only a full check can drive publishing")
    have = registry.file_sha256(registry_path)
    if rep.get("registry_sha256") != have:
        raise ReportMismatch(f"{Path(path).name}: checked registry {rep.get('registry_sha256')} but the registry is now {have}; "
                             "re-run `drift check`")
    return rep


def decide(c: dict, findings: list[dict], today: dt.date) -> tuple[bool, str]:
    """(renew?, basis or reason). Pure: reads the claim and its findings, changes nothing."""
    receipts = registry.receipts(c)
    by_receipt = {f.get("receipt", 0): f for f in findings}
    if len(findings) != len(receipts) or set(by_receipt) != set(range(len(receipts))):
        return False, "not every receipt was checked in this run"
    if c.get("review_outcome") != "supported" or not c.get("reviewed_at"):
        return False, f"no supported review by a person (outcome {c.get('review_outcome')!r})"
    if c.get("review_claim_hash") != registry.claim_hash(c):
        return False, "claim, owner, status or sources changed since the last human review"
    age = (today - registry._date(c["reviewed_at"])).days
    if age > registry.HUMAN_REVIEW_MAX_DAYS:
        return False, f"human review is {age} days old (limit {registry.HUMAN_REVIEW_MAX_DAYS}): periodic review due"
    if registry.integrity_problems(c):
        return False, "stored evidence does not match its digest"
    stale = registry.review_fetch_problems(c)
    if stale:
        return False, "the review rests on stale evidence: " + "; ".join(stale)
    if registry.review_state(c) != "valid" and registry.auto_state(c) != "valid":
        return False, "stored evidence has no valid review chain; a person must review it"
    if age < 0:
        return False, "human review is in the future"
    routine = []
    for i, r in enumerate(receipts):
        f = by_receipt[i]
        other = set(f.get("reasons") or []) - ROUTINE_REASONS
        if other:
            return False, f"receipt {i}: {', '.join(sorted(other))}"
        if f.get("old_hash") != r.get("snapshot_hash"):
            return False, f"receipt {i}: registry evidence changed since the check"
        new = f.get("new_excerpt") or ""
        if not new or registry.excerpt_sha256(new) != f.get("new_hash"):
            return False, f"receipt {i}: new excerpt missing or its digest is wrong"
        if f["new_hash"] == r.get("snapshot_hash"):
            continue
        if r["source_type"] not in ROUTINE_SOURCES:
            return False, f"receipt {i}: {r['source_type']} excerpt changed (pages are read by a person)"
        if mask(new) != mask(r.get("snapshot") or ""):
            return False, f"receipt {i}: excerpt changed beyond version numbers and dates"
        routine.append(f"receipt {i} {r.get('last_version') or '?'} -> {f.get('new_version') or '?'}")
    return True, ("version/date only: " + "; ".join(routine)) if routine else "unchanged"


def apply(c: dict, findings: list[dict], basis: str, when: dt.date) -> None:
    ok, reason = decide(c, findings, when)
    if not ok:
        raise registry.RegistryError(f"{c['id']}: automatic re-check refused: {reason}")
    by_receipt = {f.get("receipt", 0): f for f in findings}
    for i, r in enumerate(registry.receipts(c)):
        f = by_receipt[i]
        upd = {"fetched_at": when.isoformat()}
        if f.get("new_hash") and f["new_hash"] != r.get("snapshot_hash"):
            upd.update(snapshot=f["new_excerpt"], snapshot_hash=f["new_hash"],
                       last_version=f.get("new_version") or r.get("last_version"))
        registry.set_receipt(c, i, upd)
    c["auto_checked_at"] = when.isoformat()
    c["auto_check_basis"] = basis
    c["auto_check_hash"] = registry.auto_check_hash(c)
    if registry.auto_state(c) != "valid":  # belt and braces: never write a re-check that would not hold
        raise registry.RegistryError(f"{c['id']}: automated re-check would not be valid; refusing to write it")


def next_version(today: dt.date, versions: list[str]) -> str:
    base = f"v{today:%Y.%m.%d}"
    same = [v for v in versions if v == base or v.startswith(base + ".")]
    if not same:
        return base
    n = max(mapgen.version_key(v)[1] for v in same) + 1
    return f"{base}.{n}"


def needs_version(claims: list[dict], today: dt.date, maps_dir: Path) -> tuple[bool, str]:
    p = mapgen.latest_map(maps_dir)
    if p is None:
        return True, "no published map"
    state, pub, why = mapgen.publication_state(p)
    if state != "current":
        return True, f"published map is not a current-schema publication ({why})"
    try:
        cand = mapgen.build_map(claims, mapgen.load_controls(), pub["version"], mapgen.load_governance(), mapgen.load_copy())
    except mapgen.MapError as e:
        return True, f"registry no longer builds the published layout ({e})"
    if mapgen.content(cand) != mapgen.content(pub):
        return True, f"content differs from {pub['version']} (reviewed registry changes)"
    left = (dt.date.fromisoformat(pub["expires"]) - today).days
    if left <= RENEW_DAYS:
        return True, f"{pub['version']} re-check due in {left} day(s)"
    return False, f"{pub['version']} content unchanged, re-check due in {left} day(s)"


def insert_changelog(path: Path, entry: str) -> None:
    text = path.read_text(encoding="utf-8")
    i = text.find("\n## ")
    text = (text.rstrip("\n") + "\n\n" + entry) if i < 0 else text[:i + 1] + entry + "\n" + text[i + 1:]
    path.write_text(text, encoding="utf-8", newline="\n")


def build_version(claims: list[dict], version: str, today: dt.date, why: str, summary: dict,
                  maps_dir: Path, registry_path: Path | None = None) -> dict:
    mapgen.preflight(claims, version, today, mapgen.existing_versions(maps_dir))
    governance = mapgen.load_governance()
    m = mapgen.build_map(claims, mapgen.load_controls(), version, governance, mapgen.load_copy())
    mapgen.validate_map(m, claims)
    maps_dir = Path(maps_dir).resolve()
    maps_dir.mkdir(parents=True, exist_ok=True)
    final = maps_dir / version
    # Everything is prepared off the published path. No incomplete JSON can become latest_map().
    with tempfile.TemporaryDirectory(prefix=".publish-", dir=maps_dir) as td:
        stage = Path(td)
        out = mapgen.write_map(m, stage)
        try:
            r = subprocess.run([sys.executable, str(registry.ROOT / "render" / "render_map.py"), str(out)],
                               capture_output=True, text=True, encoding="utf-8", timeout=600)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise PublicationError(f"PNG render failed: {type(e).__name__}") from e
        if r.returncode != 0:
            raise PublicationError(f"PNG render failed: {r.stderr.strip()[:400]}")
        errors = mapgen.verify_image(out.parent, m)
        if errors:
            raise PublicationError("; ".join(errors))
        replacements = {}
        if registry_path is not None:
            staged_registry = stage / "claims.yaml"
            registry.save(claims, staged_registry)
            replacements[Path(registry_path)] = staged_registry
        if maps_dir == mapgen.MAPS_DIR.resolve():
            staged_md, staged_readme, staged_log = (stage / n for n in ("MAP.md", "README.md", "CHANGELOG.md"))
            staged_md.write_text(mapgen.render_map_markdown(m), encoding="utf-8", newline="\n")
            shutil.copyfile(mapgen.README, staged_readme)
            if not mapgen.update_readme(m, staged_readme):
                raise PublicationError("README map markers missing")
            changelog = registry.ROOT / "CHANGELOG.md"
            shutil.copyfile(changelog, staged_log)
            insert_changelog(staged_log, "\n".join([
                f"## {version} (automatic)", "",
                f"Published by the weekly job: {why}.",
                f"- Tools and labels: {'changed (reviewed registry edits)' if 'content differs' in why else 'unchanged'}. "
                f"{m['counts']['tools']} tools; oldest check {m['oldest_check']}; re-check due {m['expires']}.",
                f"- This run: {summary['renewed']} claim(s) re-checked automatically, {summary['needs_person']} waiting for a person.",
                "- Media: map.png. Videos are rendered on demand for posts.", ""]))
            replacements.update({mapgen.MAP_MD: staged_md, mapgen.README: staged_readme, changelog: staged_log})
        before = {p: p.read_bytes() if p.exists() else None for p in replacements}
        promoted = False
        try:
            if final.exists():
                raise PublicationError(f"{version} already exists")
            out.parent.rename(final)
            promoted = True
            for target, staged in replacements.items():
                os.replace(staged, target)
        except BaseException:
            # Roll back this transaction only. A killed process is caught by the weekly dirty-tree
            # and verification gates; multi-file filesystem updates cannot be crash-atomic.
            for target, contents in before.items():
                if contents is None:
                    target.unlink(missing_ok=True)
                else:
                    target.write_bytes(contents)
            if promoted and final.parent.resolve() == maps_dir:
                shutil.rmtree(final)
            raise
    return m


def render_md(doc: dict) -> str:
    md = report.md_escape
    L = [f"# Automated publishing {doc['run_id']}", "",
         f"Check report `{doc['report_run_id']}` ({doc['checked_on']}). {doc['summary']['renewed']} claim(s) re-checked "
         f"automatically, {doc['summary']['needs_person']} waiting for a person.", "",
         f"Map: {doc['version']['action']} ({md(doc['version']['why'])}).", ""]
    if doc["needs_person"]:
        L += ["## Needs a person", "", "| id | tool | on map | why |", "|---|---|---|---|"]
        L += [f"| {md(x['id'])} | {md(x['tool'])} | {'yes' if x['on_map'] else 'candidate'} | {md(x['why'])} |"
              for x in doc["needs_person"]] + [""]
    else:
        L += ["## Needs a person", "", "Nothing.", ""]
    L += ["## Re-checked automatically", "", "| id | basis |", "|---|---|"]
    L += [f"| {md(x['id'])} | {md(x['basis'])} |" for x in doc["renewed"]] + [""]
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="drift auto", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--report", type=Path, required=True, help="the full check report written by this run")
    ap.add_argument("--registry", type=Path, default=registry.REGISTRY)
    ap.add_argument("--maps-dir", type=Path, default=mapgen.MAPS_DIR)
    ap.add_argument("--reports-dir", type=Path, default=registry.REPORTS_DIR)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-build", action="store_true", help="renew claims but never build a version")
    args = ap.parse_args(argv)
    try:
        claims = registry.load(args.registry)
        rep = _load_report(args.report, args.registry)
    except ReportMismatch as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_SETUP
    except (registry.RegistryError, OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_ERROR
    today = dt.date.fromisoformat(rep["started_at"][:10])
    by_claim: dict[str, list[dict]] = {}
    for f in rep["findings"]:
        by_claim.setdefault(f["id"], []).append(f)

    renewed, needs = [], []
    for c in claims:
        ok, why = decide(c, by_claim.get(c["id"], []), today)
        if ok:
            if not args.dry_run:
                apply(c, by_claim[c["id"]], why, today)
            renewed.append({"id": c["id"], "basis": why})
        else:
            needs.append({"id": c["id"], "tool": c["tool"], "on_map": c.get("on_map", True), "why": why})
    summary = {"renewed": len(renewed), "needs_person": len(needs)}
    version = {"action": "none", "why": ""}
    try:
        need, why = needs_version(claims, today, args.maps_dir)
        version["why"] = why
        if need and not args.no_build:
            v = next_version(today, mapgen.existing_versions(args.maps_dir))
            if args.dry_run:
                version["action"] = f"would build {v}"
            else:
                try:
                    m = build_version(claims, v, today, why, summary, args.maps_dir, args.registry)
                    version.update(action=f"built {v}", expires=m["expires"])
                except mapgen.MapError as e:
                    version.update(action="blocked", why=f"{why}; build refused: {e}")
                    needs.append({"id": "(map)", "tool": "new version", "on_map": True, "why": version["why"]})
                    summary["needs_person"] = len(needs)
        if not args.dry_run and not version["action"].startswith("built "):
            registry.save(claims, args.registry)
    except (registry.RegistryError, mapgen.MapError, PublicationError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_ERROR

    doc = {"run_id": f"{rep['run_id']}-auto", "report_run_id": rep["run_id"], "checked_on": today.isoformat(),
           "summary": summary, "version": version, "needs_person": needs, "renewed": renewed}
    print(f"drift auto: {summary['renewed']} re-checked automatically, {summary['needs_person']} need a person; "
          f"map: {version['action']} ({version['why']})")
    for x in needs:
        print(f"  needs a person: {x['id']} ({x['tool']}): {x['why']}")
    if not args.dry_run:
        out = Path(args.reports_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{doc['run_id']}.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n",
                                                   encoding="utf-8", newline="\n")
        (out / f"{doc['run_id']}.md").write_text(render_md(doc), encoding="utf-8", newline="\n")
    return EXIT_NEEDS_PERSON if needs else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
