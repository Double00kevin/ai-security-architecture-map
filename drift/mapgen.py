"""`drift map`: generate a versioned map.json from reviewed evidence, and refuse what isn't.

    python -m drift map build --version v2026.10.04   # writes maps/v2026.10.04/map.json, MAP.md, README block
    python -m drift map check                          # exit 1 if the newest map is expired (or missing)
    python -m drift map check --today 2026-11-01       # replay a date (tests, CI)
    python -m drift map verify                         # rebuild the newest version into a temp dir and diff

A map's validity is bound to reviewed evidence, not to its version string. `build` refuses when:
- any on-map claim lacks a valid check (a person's `supported` review, or an automated re-check that
  carries it forward; see registry.py), has a
  receipt without snapshot/hash, or has an assertion with no supporting receipt;
- the version date is in the future, or earlier than the newest existing version;
- a layer is outside 1..12, or a (layer, tool) pair appears twice;
- the version directory already exists (same-day re-issues use vYYYY.MM.DD.N);
- the map would already be expired on the day it is built (an old review cannot be published as current).

`expires` = min(oldest check among on-map claims + 30 days, version date + 30 days), so
an old review cannot hide behind a fresh version number. Governance entries past `review_due` are
warned about.

`verify` fails when any on-map claim is no longer publishable, when the registry would now show
different tools or labels than the published map (ship a new version), or when MAP.md, the README
block or the PNG are not what the published map.json renders to.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import difflib
import json
import re
import sys
from pathlib import Path

import yaml

from . import registry

MAPS_DIR = registry.ROOT / "maps"
CONTROLS = registry.ROOT / "registry" / "controls.yaml"
GOVERNANCE = registry.ROOT / "registry" / "governance.yaml"
COPY = registry.ROOT / "registry" / "copy.yaml"
VERSION_RE = re.compile(r"v(\d{4})\.(\d{2})\.(\d{2})(?:\.(\d+))?")  # optional .N for a same-day re-issue
SCHEMA_VERSION = 3  # 3: per-tool checked_at/checked_by (person or automated re-check); oldest_check


class MapError(Exception):
    pass


def version_date(version: str) -> dt.date:
    m = VERSION_RE.fullmatch(version)
    if not m:
        raise MapError(f"version must look like vYYYY.MM.DD or vYYYY.MM.DD.N, got {version!r}")
    try:
        return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError as e:
        raise MapError(f"version {version!r} is not a real date: {e}") from None


def version_key(version: str) -> tuple:
    m = VERSION_RE.fullmatch(version)
    return (version_date(version), int(m.group(4) or 0))


def load_controls(path: Path = CONTROLS) -> list[dict]:
    with Path(path).open("r", encoding="utf-8") as f:
        controls = yaml.safe_load(f)["controls"]
    if [c["layer"] for c in controls] != list(registry.LAYERS):
        raise MapError("controls.yaml must have exactly layers 1..12 in order")
    return controls


def load_governance(path: Path = GOVERNANCE) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)["governance"]


def load_copy(path: Path = COPY) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)["copy"]


def existing_versions(maps_dir: Path = MAPS_DIR) -> list[str]:
    d = Path(maps_dir)
    if not d.exists():
        return []
    return sorted((p.name for p in d.iterdir() if p.is_dir() and VERSION_RE.fullmatch(p.name)), key=version_key)


def preflight(claims: list[dict], version: str, today: dt.date, versions: list[str]) -> None:
    """Every reason this map may not be built, raised together so one run shows all of them."""
    problems = []
    date = version_date(version)
    if date > today:
        problems.append(f"version date {date} is in the future (today is {today})")
    if versions:
        newest = max(versions, key=version_key)
        if version_date(newest) > date:
            problems.append(f"version {version} is earlier than the newest existing version {newest}")
        elif version_key(version) <= version_key(newest):
            problems.append(f"version {version} does not sort after the newest existing version {newest} "
                            f"(same-day re-issues use {newest.split('.')[0]}.{newest.split('.')[1]}.{newest.split('.')[2]}.N)")
    seen = collections.Counter((c["layer"], c["tool"]) for c in registry.on_map(claims))
    for (layer, tool), n in seen.items():
        if n > 1:
            problems.append(f"duplicate on-map tool {tool!r} in layer {layer}")
    for c in registry.on_map(claims):
        if c["layer"] not in registry.LAYERS:
            problems.append(f"{c['id']}: layer {c['layer']} outside 1..12")
        why = registry.publishable(c)
        if why:
            problems.append(f"{c['id']}: {'; '.join(why)}")
        else:
            when, _ = registry.last_check(c)
            if when and when > today:
                problems.append(f"{c['id']}: its newest check ({when}) is in the future")
    if not problems:
        expires, oldest = expiry(claims, version)
        if expires < today:
            problems.append(f"this map would already be expired on {today}: it expires {expires} "
                            f"(oldest check {oldest}); re-check the oldest claims first")
    if problems:
        raise MapError("map build refused:\n  - " + "\n  - ".join(problems))


def expiry(claims: list[dict], version: str) -> tuple[dt.date, str | None]:
    """min(oldest check on the map + 30 days, version date + 30 days). A check is a person's supported
    review or a valid automated re-check, whichever is newer for that claim."""
    by_version = version_date(version) + dt.timedelta(days=registry.STALE_DAYS)
    checked = [d for d, _ in (registry.last_check(c) for c in registry.on_map(claims)) if d]
    if not checked:
        return by_version, None
    oldest = min(checked)
    return min(by_version, oldest + dt.timedelta(days=registry.STALE_DAYS)), oldest.isoformat()


def oldest_human_review(claims: list[dict]) -> str | None:
    dates = [registry._date(c["reviewed_at"]) for c in registry.on_map(claims)
             if c.get("reviewed_at") and c.get("review_outcome") == "supported"]
    return min(dates).isoformat() if dates else None


def _event_label(ev: dict | None) -> str | None:
    if not ev:
        return None
    kind = {"acquisition_completed": "acquired by", "acquisition_agreed": "agreed to be acquired by",
            "merger": "merged with", "rename": "renamed by", "divestiture": "divested to"}.get(ev["kind"], ev["kind"])
    return f"{kind} {ev['counterparty']} ({ev.get('date') or 'date unknown'})"


def build_map(claims: list[dict], controls: list[dict], version: str, governance: list[dict] | None = None,
              copy: dict | None = None) -> dict:
    date = version_date(version)
    claims = registry.on_map(claims)  # candidates (on_map: false) never render
    layers = []
    for ctl in controls:
        n = ctl["layer"]
        tools = [c for c in claims if c["layer"] == n]  # registry order is display order
        names = [c["layer_name"] for c in tools]
        if names and any(nm != ctl["name"] for nm in names):
            raise MapError(f"layer {n}: registry layer_name {set(names)} != controls name {ctl['name']!r}")
        layers.append({
            "number": n,
            "name": ctl["name"],
            "control": ctl["control"],
            "tools": [{
                "name": c["tool"],
                "id": c["id"],
                "status": c["status"],
                "owner": c.get("owner"),
                "ownership": _event_label(c.get("ownership_event")),
                "source_url": c["source_url"],
                "checked_at": str(registry.last_check(c)[0] or ""),
                "checked_by": registry.last_check(c)[1] or "",
                "reviewed_at": str(c.get("reviewed_at") or ""),
                "review_hash": c.get("review_hash"),
                "check_hash": c.get("auto_check_hash") if registry.last_check(c)[1] == "auto" else c.get("review_hash"),
            } for c in tools],
        })
    counts = [len(layer["tools"]) for layer in layers]
    expires, oldest = expiry(claims, version)
    return {
        "schema_version": SCHEMA_VERSION,
        "version": version,
        "date": date.isoformat(),
        "expires": expires.isoformat(),
        "oldest_check": oldest,
        "oldest_review": oldest_human_review(claims),
        "trust_window_days": registry.STALE_DAYS,
        "title": "AI Architecture Map",
        "author": "@00Kevin",
        "counts": {"layers": len(layers), "tools": sum(counts), "controls": len(layers), "per_layer": counts},
        "layers": layers,
        "governance": [{"name": g["name"], "short": g.get("short") or g["name"], "source_url": g["source_url"]}
                       for g in (governance or [])],
        "copy": dict(copy or {}),
    }


def validate_map(m: dict, claims: list[dict], dates: bool = True) -> None:
    """Every registry tool appears exactly once, spelled exactly the same, in its own layer; every
    serialized count is recomputed from the map's own contents, never trusted. With dates=True (build
    time) expires and the oldest check are recomputed from the registry too; a published map is not
    held to dates the registry has since moved past (weekly re-checks renew claims after publication)."""
    want = collections.Counter((c["layer"], c["tool"]) for c in registry.on_map(claims))
    got = collections.Counter((layer["number"], t["name"]) for layer in m["layers"] for t in layer["tools"])
    if want != got:
        raise MapError(f"map/registry mismatch: missing {sorted((want - got).elements())}, extra {sorted((got - want).elements())}")
    dups = [k for k, n in got.items() if n > 1]
    if dups:
        raise MapError(f"duplicate tools on the map: {sorted(dups)}")
    numbers = [layer["number"] for layer in m["layers"]]
    if numbers != list(registry.LAYERS):
        raise MapError(f"map layers must be 1..12 in order, got {numbers}")
    per_layer = [len(layer["tools"]) for layer in m["layers"]]
    counts = m.get("counts") or {}
    expected = {"layers": len(m["layers"]), "controls": len(m["layers"]), "tools": sum(per_layer), "per_layer": per_layer}
    wrong = {k: (counts.get(k), v) for k, v in expected.items() if counts.get(k) != v}
    if wrong:
        raise MapError("serialized counts do not match the map's contents: "
                       + ", ".join(f"{k} says {have}, actually {want_}" for k, (have, want_) in wrong.items()))
    if per_layer != registry.LAYER_COUNTS:  # editorial policy, kept separate from the arithmetic above
        raise MapError(f"per-layer counts {per_layer} != the editorial policy {registry.LAYER_COUNTS} "
                       f"(registry.LAYER_COUNTS; change it deliberately when a tool joins or leaves the map)")
    if dates and m.get("schema_version", 1) >= 3:
        exp, oldest = expiry(claims, m["version"])
        if m.get("expires") != exp.isoformat() or m.get("oldest_check") != oldest:
            raise MapError(f"expires/oldest_check {m.get('expires')}/{m.get('oldest_check')} do not match the "
                           f"checks ({exp.isoformat()}/{oldest})")
    validate_publication_dates(m)


def validate_publication_dates(m: dict) -> None:
    """Validate the publication's own dates, independently of later registry re-checks."""
    try:
        day = version_date(m["version"])
        if m["date"] != day.isoformat() or m["trust_window_days"] != registry.STALE_DAYS:
            raise MapError("publication date/trust window does not match policy")
        expiry_date = dt.date.fromisoformat(m["expires"])
        limit = day + dt.timedelta(days=registry.STALE_DAYS)
        schema = m.get("schema_version", 1)
        if schema not in (1, 2, 3):
            raise MapError(f"unsupported map schema {schema}")
        if schema >= 2:
            tools = [t for layer in m["layers"] for t in layer["tools"]]
            if not tools:
                raise MapError("publication has no checked tools")
            reviews = [dt.date.fromisoformat(t["reviewed_at"]) for t in tools]
            checks = [dt.date.fromisoformat(t["checked_at"]) for t in tools] if schema >= 3 else reviews
            if any(review > checked or checked > day for review, checked in zip(reviews, checks)):
                raise MapError("publication checks must be between the human review and version date")
            if m["oldest_review"] != min(reviews).isoformat():
                raise MapError("oldest_review does not match the published tool reviews")
            if schema >= 3:
                if m["oldest_check"] != min(checks).isoformat():
                    raise MapError("oldest_check does not match the published tool checks")
                for t, reviewed, checked in zip(tools, reviews, checks):
                    if t["checked_by"] not in ("person", "auto"):
                        raise MapError("invalid checked_by in publication")
                    if t["checked_by"] == "person" and checked != reviewed:
                        raise MapError("person check date differs from human review")
                    if t["checked_by"] == "auto" and (checked - reviewed).days > registry.HUMAN_REVIEW_MAX_DAYS:
                        raise MapError("automated check exceeds the human review renewal window")
            limit = min(limit, min(checks) + dt.timedelta(days=registry.STALE_DAYS))
        if expiry_date != limit:
            raise MapError(f"publication expires {expiry_date}, but its recorded checks require {limit}")
    except (KeyError, TypeError, ValueError) as e:
        raise MapError(f"invalid publication dates: {e}") from e


def governance_warnings(governance: list[dict], today: dt.date) -> list[str]:
    out = []
    for g in governance:
        due = g.get("review_due")
        if not due:
            out.append(f"governance {g.get('short') or g['name']}: no review_due recorded")
        elif registry._date(due) < today:
            out.append(f"governance {g.get('short') or g['name']}: review was due {due}")
    return out


MAP_MD = registry.ROOT / "MAP.md"
README = registry.ROOT / "README.md"
README_BEGIN, README_END = "<!-- map:begin (generated by `python -m drift map build`; do not edit by hand) -->", "<!-- map:end -->"


def render_map_markdown(m: dict) -> str:
    """MAP.md: the whole map as text, so the repo says what it covers without opening the PNG."""
    if m.get("schema_version", 1) >= 3:
        return _render_map_markdown_v3(m)
    copy = m.get("copy", {})
    L = [f"# {copy.get('title', m.get('title', 'AI Architecture Map'))} — {copy.get('title_accent', '')}".rstrip(" —"),
         "", f"Version **{m['version']}** (generated {m['date']}, trusted until {m['expires']}). "
         f"{m['counts']['tools']} tools across {m['counts']['layers']} layers, one security control per layer. "
         f"Every tool has a receipt in `registry/claims.yaml` and a review of that receipt"
         + (f"; the oldest review is from {m['oldest_review']}." if m.get("oldest_review") else "."), "",
         f"![{copy.get('title', 'AI Architecture Map')} {m['version']}](maps/{m['version']}/map.png)", "",
         copy.get("subtitle", ""), ""]
    for layer in m["layers"]:
        L += [f"## {layer['number']:02d} · {layer['name']}", "",
              f"**Security control:** {layer['control']}", "",
              "| Tool | Status | Owner | Receipt | Reviewed |", "|---|---|---|---|---|"]
        for t in layer["tools"]:
            owner = t.get("owner") or ""
            if t.get("ownership"):
                owner = f"{owner} ({t['ownership']})" if owner else t["ownership"]
            L.append(f"| {t['name']} | {t['status']} | {owner} | [{t['id']}]({t['source_url']}) | {t.get('reviewed_at', '')} |")
        L.append("")
    if m.get("governance"):
        L += [f"## {copy.get('governance_label', 'Govern it all').title()}", "",
              "The frameworks the controls draw on.", ""]
        L += [f"- [{g['name']}]({g['source_url']})" for g in m["governance"]] + [""]
    L += ["## How to read a receipt", "",
          "Each row links to the primary source the claim rests on. `registry/claims.yaml` also holds the short excerpt "
          "that was read, its SHA-256, the version seen, the date it was fetched, which assertions it supports, and the "
          "review record of the person who read it. `python -m drift check` re-fetches every source weekly and flags a "
          "new version, a changed excerpt, a lifecycle signal, or a review older than 30 days.", ""]
    return "\n".join(L)


def _render_map_markdown_v3(m: dict) -> str:
    copy = m.get("copy", {})
    who = {"person": "review", "auto": "automated re-check"}
    L = [f"# {copy.get('title', m.get('title', 'AI Architecture Map'))} — {copy.get('title_accent', '')}".rstrip(" —"),
         "", f"Version **{m['version']}** (generated {m['date']}, re-check due {m['expires']}). "
         f"{m['counts']['tools']} tools across {m['counts']['layers']} layers, one security control per layer. "
         f"Every tool has a receipt in `registry/claims.yaml`, read by a person"
         + (f" (oldest human review {m['oldest_review']})" if m.get("oldest_review") else "")
         + (f" and re-checked since; the oldest check behind this version is from {m['oldest_check']}." if m.get("oldest_check") else "."),
         "", f"![{copy.get('title', 'AI Architecture Map')} {m['version']}](maps/{m['version']}/map.png)", "",
         copy.get("subtitle", ""), ""]
    for layer in m["layers"]:
        L += [f"## {layer['number']:02d} · {layer['name']}", "",
              f"**Security control:** {layer['control']}", "",
              "| Tool | Status | Owner | Receipt | Last check | Human review |", "|---|---|---|---|---|---|"]
        for t in layer["tools"]:
            owner = t.get("owner") or ""
            if t.get("ownership"):
                owner = f"{owner} ({t['ownership']})" if owner else t["ownership"]
            check = f"{t.get('checked_at', '')} ({who.get(t.get('checked_by'), t.get('checked_by', ''))})" if t.get("checked_at") else ""
            L.append(f"| {t['name']} | {t['status']} | {owner} | [{t['id']}]({t['source_url']}) | {check} | {t.get('reviewed_at', '')} |")
        L.append("")
    if m.get("governance"):
        L += [f"## {copy.get('governance_label', 'Govern it all').title()}", "",
              "The frameworks the controls draw on.", ""]
        L += [f"- [{g['name']}]({g['source_url']})" for g in m["governance"]] + [""]
    L += ["## How to read a receipt", "",
          "Each row links to the primary source the claim rests on. `registry/claims.yaml` also holds the short excerpt "
          "that was read, its SHA-256, the version seen, the date it was fetched, which assertions it supports, and the "
          "review record of the person who read it. Every Saturday `python -m drift check` re-fetches every source. "
          "Routine changes (a new version number or date, nothing else) are re-checked automatically and the claim "
          "keeps its person's review for up to 180 days; anything else (a changed page, a lifecycle or ownership "
          "signal, a source that can't be reached) waits for a person. \"Last check\" says which kind of check it was.", ""]
    return "\n".join(L)


def render_readme_block(m: dict) -> str:
    """Compact table for the README, between the map markers."""
    L = [README_BEGIN, "",
         f"[![map {m['version']}](maps/{m['version']}/map.png)](maps/{m['version']}/map.png)", "",
         f"Current version **{m['version']}**, trusted until **{m['expires']}**. Full text with receipts: [MAP.md](MAP.md).", "",
         "| # | Layer | Tools | Security control |", "|---|---|---|---|"]
    for layer in m["layers"]:
        tools = " · ".join(t["name"] for t in layer["tools"])
        L.append(f"| {layer['number']:02d} | {layer['name']} | {tools} | {layer['control']} |")
    L += ["", README_END]
    return "\n".join(L)


def readme_block(text: str) -> str | None:
    a, b = text.find(README_BEGIN), text.find(README_END)
    return None if a < 0 or b < 0 else text[a:b + len(README_END)]


def update_readme(m: dict, path: Path = README) -> bool:
    """Replace the generated block in README.md. Returns False if the markers are missing."""
    p = Path(path)
    s = p.read_text(encoding="utf-8")
    a, b = s.find(README_BEGIN), s.find(README_END)
    if a < 0 or b < 0:
        return False
    s = s[:a] + render_readme_block(m) + s[b + len(README_END):]
    p.write_text(s, encoding="utf-8", newline="\n")
    return True


def map_json_text(m: dict) -> str:
    return json.dumps(m, indent=2, ensure_ascii=False) + "\n"


def write_map(m: dict, maps_dir: Path = MAPS_DIR) -> Path:
    out_dir = Path(maps_dir) / m["version"]
    if out_dir.exists():
        raise MapError(f"{m['version']} already exists; published versions are never rewritten "
                       f"(same-day re-issue: {m['version']}.N)")
    out_dir.mkdir(parents=True)
    out = out_dir / "map.json"
    out.write_text(map_json_text(m), encoding="utf-8", newline="\n")
    return out


def latest_map(maps_dir: Path = MAPS_DIR) -> Path | None:
    maps_dir = Path(maps_dir)
    if not maps_dir.exists():
        return None
    candidates = [p / "map.json" for p in maps_dir.iterdir() if p.is_dir() and VERSION_RE.fullmatch(p.name)]
    candidates = [p for p in candidates if p.exists()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: version_key(p.parent.name))


def check_expiry(map_path: Path | None, today: dt.date) -> tuple[bool, str]:
    if map_path is None:
        return False, "no map found: run `python -m drift map build --version vYYYY.MM.DD`"
    try:
        m = json.loads(Path(map_path).read_text(encoding="utf-8"))
        validate_publication_dates(m)
        if version_date(m["version"]) > today:
            raise MapError("publication version is in the future")
    except (OSError, ValueError, MapError) as e:
        return False, f"invalid map: {e}"
    expires = dt.date.fromisoformat(m["expires"])
    left = (expires - today).days
    if left < 0:
        return False, f"{m['version']} EXPIRED {-left} day(s) ago (expires {m['expires']}); ship a new version"
    return True, f"{m['version']} valid, {left} day(s) left (expires {m['expires']})"


CONTENT_TOOL_KEYS = ("name", "id", "status", "owner", "ownership", "source_url")


def content(m: dict) -> dict:
    """What a reader sees on a map version: layers, tools and their labels, controls, governance and
    copy. Check dates are not content: weekly re-checks renew them without a new version."""
    return {
        "layers": [{"number": layer["number"], "name": layer["name"], "control": layer["control"],
                    "tools": [{k: t.get(k) for k in CONTENT_TOOL_KEYS} for t in layer["tools"]]}
                   for layer in m["layers"]],
        "governance": m.get("governance", []),
        "copy": m.get("copy", {}),
    }


def verify_image(directory: Path, m: dict) -> list[str]:
    """Compare decoded image pixels and drawn-text sidecar, not just filenames or requested text."""
    from PIL import Image
    from render import render_map

    absent = [n for n in ("map.png", "map.txt") if not (directory / n).is_file()]
    if absent:
        return [f"{m['version']}: {', '.join(absent)} missing; render the map before publication"]
    errors = []
    try:
        expected = render_map.render(m)
        with Image.open(directory / "map.png") as actual:
            if actual.format != "PNG" or actual.size != expected.im.size:
                errors.append("map.png format or dimensions differ from a rebuild")
            elif actual.convert("RGBA").tobytes() != expected.im.convert("RGBA").tobytes():
                errors.append("map.png pixels differ from a rebuild")
        if (directory / "map.txt").read_text(encoding="utf-8") != "\n".join(expected.drawn) + "\n":
            errors.append("map.txt (PNG sidecar) differs from a rebuild")
    except (OSError, ValueError, Image.DecompressionBombError) as e:
        errors.append(f"invalid map.png or sidecar: {type(e).__name__}: {e}")
    return errors


def verify(maps_dir: Path = MAPS_DIR, registry_path: Path = registry.REGISTRY, readme: Path = README,
           map_md: Path = MAP_MD, render: bool = True) -> tuple[bool, list[str]]:
    """Check the newest published version three ways:
    1. evidence: every on-map claim is publishable now (valid, supported check; digests match);
    2. content: the tools, labels, controls, governance and copy a rebuild from today's registry would
       show equal what the published map shows (a change needs a new version);
    3. artifacts: dates obey the publication policy; MAP.md, the README block, PNG pixels and sidecar
       are exactly what the published map.json renders to.
    Maps from before review records existed (schema 1) are reported as legacy and skipped."""
    p = latest_map(maps_dir)
    if p is None:
        return False, ["no map found"]
    committed = json.loads(p.read_text(encoding="utf-8"))
    version = committed["version"]
    if committed.get("schema_version", 1) < 2:
        return True, [f"{version} is a legacy schema-{committed.get('schema_version', 1)} map built before "
                      f"review records existed; not reproducible from current inputs (skipped). The next build is checked."]
    claims = registry.load(registry_path)
    diffs: list[str] = []
    unpublishable = [f"{c['id']}: {'; '.join(why)}" for c in registry.on_map(claims) if (why := registry.publishable(c))]
    if unpublishable:
        diffs.append(f"{version} rests on {len(unpublishable)} on-map claim(s) that are no longer "
                     "publishable (a person must review them):\n  - " + "\n  - ".join(unpublishable))
    try:
        validate_map(committed, claims, dates=False)
    except MapError as e:
        diffs.append(str(e))

    def cmp(name: str, want: str, got: str, how: str = "differs from what the published map.json renders to") -> None:
        if want != got:
            diffs.append(f"{name} {how}:\n" + "".join(difflib.unified_diff(
                want.splitlines(True), got.splitlines(True), f"committed/{name}", f"expected/{name}", n=1))[:4000])

    rebuilt = build_map(claims, load_controls(), version, load_governance(), load_copy())
    cmp("map content", json.dumps(content(committed), indent=1, ensure_ascii=False),
        json.dumps(content(rebuilt), indent=1, ensure_ascii=False),
        "no longer matches the registry (ship a new version)")
    cmp("MAP.md", Path(map_md).read_text(encoding="utf-8"), render_map_markdown(committed))
    cmp("README map block", readme_block(Path(readme).read_text(encoding="utf-8")) or "", render_readme_block(committed))
    if render:
        diffs.extend(verify_image(p.parent, committed))
    return not diffs, diffs or [f"{version}: every on-map claim publishable; content matches the registry; "
                                f"publication dates valid; MAP.md, README block, PNG pixels and map.txt match the published map.json"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="drift map", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="generate maps/<version>/map.json from reviewed evidence")
    b.add_argument("--version", required=True, help="vYYYY.MM.DD or vYYYY.MM.DD.N")
    b.add_argument("--registry", type=Path, default=registry.REGISTRY)
    b.add_argument("--controls", type=Path, default=CONTROLS)
    b.add_argument("--governance", type=Path, default=GOVERNANCE)
    b.add_argument("--maps-dir", type=Path, default=MAPS_DIR)
    b.add_argument("--today", help="override today's date (tests, replays)")
    c = sub.add_parser("check", help="fail if the newest map is expired")
    c.add_argument("--maps-dir", type=Path, default=MAPS_DIR)
    c.add_argument("--today")
    v = sub.add_parser("verify", help="rebuild the newest version from current inputs and diff against the committed files")
    v.add_argument("--maps-dir", type=Path, default=MAPS_DIR)
    v.add_argument("--no-render", action="store_true", help="skip the PNG sidecar comparison")
    args = ap.parse_args(argv)

    try:
        if args.cmd == "build":
            today = dt.date.fromisoformat(args.today) if args.today else dt.date.today()
            claims = registry.load(args.registry)
            preflight(claims, args.version, today, existing_versions(args.maps_dir))
            governance = load_governance(args.governance)
            m = build_map(claims, load_controls(args.controls), args.version, governance, load_copy())
            validate_map(m, claims)
            for w in governance_warnings(governance, today):
                print(f"WARNING: {w}", file=sys.stderr)
            out = write_map(m, args.maps_dir)
            shown = out.relative_to(registry.ROOT) if out.is_relative_to(registry.ROOT) else out
            print(f"wrote {shown} ({m['counts']['tools']} tools, expires {m['expires']}, oldest check {m['oldest_check']})")
            if args.maps_dir == MAPS_DIR:  # only the real build touches the repo's docs
                MAP_MD.write_text(render_map_markdown(m), encoding="utf-8", newline="\n")
                print(f"wrote {MAP_MD.name}" + ("; README map block updated" if update_readme(m) else "; README has no map markers"))
            return 0
        if args.cmd == "verify":
            ok, msgs = verify(args.maps_dir, render=not args.no_render)
            for msg in msgs:
                print(("map verify: " if ok else "map verify FAILED: ") + msg)
            return 0 if ok else 1
        ok, msg = check_expiry(latest_map(args.maps_dir), dt.date.fromisoformat(args.today) if args.today else dt.date.today())
        print(("map check: " if ok else "map check FAILED: ") + msg)
        return 0 if ok else 1
    except (MapError, registry.RegistryError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
