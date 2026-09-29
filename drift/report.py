"""Report rendering for `drift check`: Markdown for humans, JSON for machines.

Every run gets its own files, reports/<run_id>.md and .json, where run_id is the UTC start time
(YYYY-MM-DDTHHMMSSZ) plus the scope for partial runs, so runs never overwrite each other. The JSON
carries the run id, the sha256 of the registry file the run read, the git commit when available, the
claim text at check time, and a `digest` over its own content that `drift triage` re-verifies.

All vendor-supplied text is escaped before it goes into Markdown, so a `|`, a backtick, a heading
marker or an HTML tag inside an excerpt cannot break the report's structure.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
import subprocess
from pathlib import Path

REASON_LABEL = {
    "version_bump": "new version",
    "section_changed": "page section changed",
    "lifecycle": "LIFECYCLE SIGNAL",
    "stale": "review due (none valid in 30 days)",
    "error": "could not verify",
    "unresolved_review": "REVIEW NOT SUPPORTED (unresolved)",
    "integrity": "EXCERPT DOES NOT MATCH ITS DIGEST",
}
STATUS_LABEL = {
    "active": "active",
    "renamed": "RENAMED",
    "acquired": "acquired",
    "deprecated": "DEPRECATED",
    "dead": "DEAD",
}
RUN_ID_RE = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{6}Z)(?:-(.+))?")


def md_escape(x: str | None) -> str:
    """Neutralise Markdown/HTML structure in untrusted text: one line, no tags, no table breaks."""
    if not x:
        return ""
    x = " ".join(str(x).split())
    x = html.escape(x, quote=False)
    return re.sub(r"([\\`*_\[\]|#~!])", r"\\\1", x)


def _short(x: str | None, n: int = 160) -> str:
    if not x:
        return ""
    x = " ".join(str(x).split())
    x = x if len(x) <= n else x[: n - 1] + "…"
    return md_escape(x)


def summarize(findings, today: dt.date, scope: str) -> dict:
    flagged = [f for f in findings if f.flagged]
    by_reason: dict[str, int] = {}
    for f in flagged:
        for r in f.reasons:
            by_reason[r] = by_reason.get(r, 0) + 1
    by_status: dict[str, int] = {}
    for f in findings:
        if f.receipt == 0:
            by_status[f.status] = by_status.get(f.status, 0) + 1
    return {
        "date": today.isoformat(),
        "scope": scope,
        "checked": len(findings),
        "claims": len({f.id for f in findings}),
        "flagged": len(flagged),
        "errors": sum(1 for f in findings if f.error),
        "by_reason": by_reason,
        "by_status": by_status,
    }


def render_text_summary(s: dict) -> str:
    reasons = ", ".join(f"{REASON_LABEL.get(k, k)}: {v}" for k, v in sorted(s["by_reason"].items())) or "none"
    return (f"drift check {s['date']} ({s['scope']}): {s['checked']} receipts checked, {s['flagged']} flagged, "
            f"{s['errors']} errors. Reasons: {reasons}.")


def git_commit(root: Path) -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10)
        sha = out.stdout.strip()
        return sha if out.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", sha) else None
    except (OSError, subprocess.SubprocessError):
        return None


def run_meta(now: dt.datetime, scope: str, registry_path: Path) -> dict:
    from . import registry

    stamp = now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    run_id = stamp if scope == "all" else f"{stamp}-{re.sub(r'[^A-Za-z0-9.-]+', '-', scope)}"
    return {
        "run_id": run_id,
        "started_at": now.astimezone(dt.timezone.utc).isoformat(timespec="seconds"),
        "scope": scope,
        "registry_sha256": registry.file_sha256(registry_path),
        "git_commit": git_commit(registry.ROOT),
    }


def content_digest(doc: dict) -> str:
    body = {k: v for k, v in doc.items() if k != "digest"}
    blob = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def render_markdown(findings, s: dict, meta: dict | None = None) -> str:
    meta = meta or {}
    lines = [f"# Drift report {meta.get('run_id', s['date'])}", "",
             f"Scope: {s['scope']}. {render_text_summary(s)}", ""]
    if meta:
        lines += [f"Run `{meta['run_id']}`, registry `{meta['registry_sha256']}`, "
                  f"commit `{meta.get('git_commit') or 'unknown'}`.", ""]
    lines += ["Flagged claims need a human re-check. This report never changes the registry; "
              "update a claim only after reading the source.", ""]
    flagged = [f for f in findings if f.flagged]
    if flagged:
        lines += ["## Flagged", "",
                  "| id | tool | status | why | was | now |", "|---|---|---|---|---|---|"]
        for f in flagged:
            why = ", ".join(REASON_LABEL.get(r, r) for r in f.reasons)
            if "unresolved_review" in f.reasons:
                why += f" (outcome {f.review_outcome}" + (f"; no receipt for {', '.join(f.unsupported_assertions)}"
                                                           if f.unsupported_assertions else "") + ")"
            was = f.old_version or f.old_excerpt
            now = f.error or f.new_version or f.new_excerpt
            tool = f.tool if f.on_map else f"{f.tool} (candidate)"
            lines.append(f"| {md_escape(f.key)} | {md_escape(tool)} | {STATUS_LABEL.get(f.status, f.status)} | {why} | "
                         f"{_short(was, 80)} | {_short(now, 80)} |")
        lines.append("")
        life = [f for f in flagged if f.lifecycle]
        if life:
            lines += ["## Lifecycle signals", ""]
            for f in life:
                lines += [f"- {md_escape(f.key)} ({md_escape(f.tool)}): " + "; ".join(_short(x, 200) for x in f.lifecycle)]
            lines.append("")
        changed = [f for f in flagged if "section_changed" in f.reasons and f.new_excerpt]
        if changed:
            lines += ["## Changed excerpts", ""]
            for f in changed:
                lines += [f"### {md_escape(f.key)} ({md_escape(f.tool)})", f"- source: <{md_escape(f.source_url)}>",
                          f"- claim: {_short(f.claim, 300)}",
                          f"- was: {_short(f.old_excerpt, 400)}", f"- now: {_short(f.new_excerpt, 400)}", ""]
    else:
        lines += ["## Flagged", "", "Nothing flagged.", ""]
    noted = [f for f in findings if f.notes]
    if noted:
        lines += ["## Notes from sources", ""] + [f"- {md_escape(f.key)}: " + "; ".join(_short(x, 200) for x in f.notes)
                                                 for f in noted] + [""]
    lines += ["## Status counts", ""] + [f"- {STATUS_LABEL.get(k, k)}: {v}" for k, v in sorted(s["by_status"].items())] + [""]
    lines += ["## All checked", "", "| id | tool | status | result | version |", "|---|---|---|---|---|"]
    for f in findings:
        res = ", ".join(REASON_LABEL.get(r, r) for r in f.reasons) or "unchanged"
        lines.append(f"| {md_escape(f.key)} | {md_escape(f.tool)} | {STATUS_LABEL.get(f.status, f.status)} | {res} | "
                     f"{_short(f.new_version or f.old_version or '', 40)} |")
    lines.append("")
    return "\n".join(lines)


def build_doc(findings, s: dict, meta: dict) -> dict:
    from .check import finding_dict

    doc = {**meta, "summary": s, "findings": [finding_dict(f) for f in findings]}
    doc["digest"] = content_digest(doc)
    return doc


def write(findings, s: dict, reports_dir: Path, meta: dict) -> tuple[Path, Path]:
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    md = reports_dir / f"{meta['run_id']}.md"
    js = reports_dir / f"{meta['run_id']}.json"
    if md.exists() or js.exists():
        raise FileExistsError(f"report {meta['run_id']} already exists; refusing to overwrite")
    md.write_text(render_markdown(findings, s, meta), encoding="utf-8", newline="\n")
    js.write_text(json.dumps(build_doc(findings, s, meta), indent=2, ensure_ascii=False) + "\n",
                  encoding="utf-8", newline="\n")
    return md, js


def list_reports(reports_dir: Path) -> list[Path]:
    """Check reports (not triage or auto outputs, not legacy date-only files), oldest first by run timestamp."""
    out = []
    for p in Path(reports_dir).glob("*.json"):
        m = RUN_ID_RE.fullmatch(p.stem)
        if m and not p.stem.endswith(("-triage", "-auto")):
            out.append((m.group(1), p.stem, p))
    return [p for _, _, p in sorted(out)]
