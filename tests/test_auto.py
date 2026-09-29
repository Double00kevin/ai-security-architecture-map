"""`drift auto`: routine weeks publish with no one in the loop; anything else waits for the owner's decision."""

import datetime as dt
import json

import pytest

from drift import auto as A
from drift import mapgen as M
from drift import registry as R
from drift import report
from drift import review
from tests.conftest import claim, reviewed

TODAY = dt.date.today()  # renders refuse expired maps, so fixtures are dated relative to the real day
CTL = [{"layer": i, "name": f"Layer {i}", "control": f"Control {i}"} for i in range(1, 13)]


def pkg(tool: str, version: str, when: dt.date) -> str:
    return f"pypi {tool} {version} uploaded {when.isoformat()}: {tool} SDK"


def mini(reviewed_on: dt.date) -> list[dict]:
    out = []
    for layer, n in enumerate(R.LAYER_COUNTS, start=1):
        for k in range(n):
            tool = f"tool-{layer}-{k}"
            snap = pkg(tool, "1.0.0", reviewed_on)
            c = claim(id=f"L{layer:02d}-t{k}", layer=layer, layer_name=f"Layer {layer}", tool=f"Tool {layer}.{k}",
                      source_url=f"https://pypi.org/project/{tool}/", snapshot=snap, snapshot_hash=R.excerpt_sha256(snap),
                      last_version="1.0.0", fetched_at=reviewed_on.isoformat())
            out.append(reviewed(c, when=reviewed_on.isoformat()))
    return out


def finding(c: dict, *, new: str | None = None, version: str | None = None, reasons=None, receipt: int = 0) -> dict:
    r = R.receipts(c)[receipt]
    new = r["snapshot"] if new is None else new
    rs = list(reasons) if reasons is not None else []
    if reasons is None and new != r["snapshot"]:
        rs = ["version_bump", "section_changed"]
    return {"id": c["id"], "key": c["id"] if receipt == 0 else f"{c['id']}#{receipt}", "receipt": receipt, "tool": c["tool"],
            "reasons": rs, "old_hash": r["snapshot_hash"], "new_hash": R.excerpt_sha256(new), "new_excerpt": new,
            "old_excerpt": r["snapshot"], "new_version": version or r.get("last_version"), "flagged": bool(rs)}


def write_report(tmp_path, reg, findings, when: dt.date = TODAY) -> "Path":
    now = dt.datetime.combine(when, dt.time(13, 0), tzinfo=dt.timezone.utc)
    meta = report.run_meta(now, "all", reg)
    doc = {**meta, "summary": {"flagged": sum(f["flagged"] for f in findings)}, "findings": findings}
    doc["digest"] = report.content_digest(doc)
    p = tmp_path / "reports" / f"{meta['run_id']}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A registry reviewed 10 days ago and a schema-3 map published then, in a scratch repo."""
    monkeypatch.setattr(M, "load_controls", lambda *a, **k: CTL)
    claims = mini(TODAY - dt.timedelta(days=10))
    reg = tmp_path / "claims.yaml"
    R.save(claims, reg)
    maps = tmp_path / "maps"
    v = f"v{TODAY - dt.timedelta(days=10):%Y.%m.%d}"
    M.write_map(M.build_map(claims, CTL, v, M.load_governance(), M.load_copy()), maps)
    return {"tmp": tmp_path, "reg": reg, "maps": maps, "claims": claims}


def run(world, findings, *extra):
    rep = write_report(world["tmp"], world["reg"], findings)
    code = A.main(["--report", str(rep), "--registry", str(world["reg"]), "--maps-dir", str(world["maps"]),
                   "--reports-dir", str(world["tmp"] / "reports"), *extra])
    out = json.loads(next((world["tmp"] / "reports").glob("*-auto.json")).read_text()) if "--dry-run" not in extra else None
    return code, out, R.load(world["reg"])


# ---- the routine test ----

def test_mask_treats_version_and_date_changes_as_routine():
    assert A.mask("pypi x 1.2.3 uploaded 2026-09-24: X SDK") == A.mask("pypi x 1.10.0rc1 uploaded 2026-09-28: X SDK")
    assert A.mask("org/x latest release v1.102.1 published 2026-09-23T06:12:28Z") == \
        A.mask("org/x latest release v1.103.0 published 2026-09-28T05:43:48Z")
    assert A.mask("pypi x 1.2.3 uploaded 2026-09-24: X SDK") != A.mask("pypi x 1.2.4 uploaded 2026-09-28: X SDK (deprecated)")


# ---- decide(): what may be renewed without the owner ----

def test_unchanged_and_version_bump_are_renewed():
    c = mini(TODAY - dt.timedelta(days=10))[0]
    assert A.decide(c, [finding(c)], TODAY) == (True, "unchanged")
    ok, basis = A.decide(c, [finding(c, new=pkg("tool-1-0", "1.1.0", TODAY), version="1.1.0")], TODAY)
    assert ok and basis.startswith("version/date only") and "1.0.0 -> 1.1.0" in basis


@pytest.mark.parametrize("change,expect", [
    ("summary", "beyond version numbers and dates"),
    ("page", "a changed page needs a new review"),
    ("lifecycle", "lifecycle"),
    ("error", "error"),
    ("edited", "changed since the last review"),
    ("old_review", "periodic review due"),
    ("unsupported", "no supported review"),
    ("missing_receipt", "not every receipt"),
    ("digest", "does not match its digest"),
])
def test_everything_else_waits_for_the_owner(change, expect):
    c = mini(TODAY - dt.timedelta(days=10))[0]
    f = [finding(c)]
    if change == "summary":
        f = [finding(c, new="pypi tool-1-0 1.1.0 uploaded 2026-09-28: now a different product", version="1.1.0")]
    elif change == "page":
        c = reviewed(claim(source_type="page_section", locator="x", snapshot="Old sentence.",
                           snapshot_hash=R.excerpt_sha256("Old sentence.")), when=(TODAY - dt.timedelta(days=3)).isoformat())
        f = [finding(c, new="New sentence.")]
    elif change == "lifecycle":
        f = [finding(c, reasons=["lifecycle"])]
    elif change == "error":
        f = [finding(c, reasons=["error"])]
    elif change == "edited":
        c["claim"] = "Tool 1.0 is the best tool ever"  # not re-reviewed
    elif change == "old_review":
        c = mini(TODAY - dt.timedelta(days=R.REVIEW_MAX_DAYS + 1))[0]
        f = [finding(c)]
    elif change == "unsupported":
        c = reviewed(claim(snapshot="x", snapshot_hash=R.excerpt_sha256("x")), when=TODAY.isoformat(), outcome="partial")
        f = [finding(c)]
    elif change == "missing_receipt":
        f = []
    elif change == "digest":
        c["snapshot"] += " (edited)"
    ok, why = A.decide(c, f, TODAY)
    assert not ok and expect in why, why


# ---- the whole step ----

def test_routine_week_renews_everything_and_publishes_nothing_when_not_due(world):
    fs = [finding(c) for c in world["claims"]]
    c0 = world["claims"][0]
    fs[0] = finding(c0, new=pkg("tool-1-0", "1.1.0", TODAY), version="1.1.0")
    code, out, after = run(world, fs)
    assert code == A.EXIT_OK and out["summary"] == {"renewed": 69, "needs_owner": 0}
    assert out["version"]["action"] == "none" and "re-check due in 20 day(s)" in out["version"]["why"]
    a0 = after[0]
    assert a0["snapshot"] == pkg("tool-1-0", "1.1.0", TODAY) and a0["last_version"] == "1.1.0"
    assert R.auto_state(a0) == "valid" and R.review_state(a0) == "void"  # the review is carried, not rewritten
    assert R.last_check(a0) == (TODAY, "auto") and R.publishable(a0) == []
    assert a0["reviewed_by"] == "tester" and a0["reviewed_at"] == (TODAY - dt.timedelta(days=10)).isoformat()


def test_a_page_change_waits_and_the_rest_still_renews(world):
    fs = [finding(c) for c in world["claims"]]
    fs[5] = finding(world["claims"][5], reasons=["lifecycle"])
    code, out, after = run(world, fs)
    assert code == A.EXIT_NEEDS_OWNER
    assert [x["id"] for x in out["needs_owner"]] == [world["claims"][5]["id"]]
    assert "auto_checked_at" not in after[5] and R.publishable(after[5]) == []  # untouched, still valid on its old check
    assert out["summary"]["renewed"] == 68


def test_publishes_a_new_version_when_the_published_one_is_close_to_its_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr(M, "load_controls", lambda *a, **k: CTL)
    old = TODAY - dt.timedelta(days=25)
    claims = mini(old)
    reg = tmp_path / "claims.yaml"
    R.save(claims, reg)
    maps = tmp_path / "maps"
    M.write_map(M.build_map(claims, CTL, f"v{old:%Y.%m.%d}", M.load_governance(), M.load_copy()), maps)
    world = {"tmp": tmp_path, "reg": reg, "maps": maps, "claims": claims}
    code, out, after = run(world, [finding(c) for c in claims])
    assert code == A.EXIT_OK and out["version"]["action"] == f"built v{TODAY:%Y.%m.%d}"
    m = json.loads((maps / f"v{TODAY:%Y.%m.%d}" / "map.json").read_text())
    assert m["schema_version"] == M.SCHEMA_VERSION and m["oldest_check"] == TODAY.isoformat()
    assert m["expires"] == (TODAY + dt.timedelta(days=30)).isoformat()
    assert m["oldest_review"] == old.isoformat()  # the review date is still shown, honestly
    assert all(t["checked_by"] == "auto" for layer in m["layers"] for t in layer["tools"])
    assert (maps / f"v{TODAY:%Y.%m.%d}" / "map.png").exists() and (maps / f"v{TODAY:%Y.%m.%d}" / "map.txt").exists()


def test_publishes_a_new_version_when_a_reviewed_change_alters_what_readers_see(world):
    c = world["claims"][0]
    c.update(owner="BigCo", assertions=["availability", "ownership"], supports=["availability", "ownership"],
             fetched_at=TODAY.isoformat())  # re-taken before the review, as `drift snapshot` would
    review.record(c, "supported", "tester", TODAY)
    R.save(world["claims"], world["reg"])
    code, out, _ = run(world, [finding(x) for x in world["claims"]])
    assert out["version"]["action"].startswith("built ") and "content differs" in out["version"]["why"]


def test_never_builds_when_the_newest_check_would_be_expired(tmp_path, monkeypatch):
    """A claim that can't be re-checked keeps its old check; once that is past 30 days, no version is built."""
    monkeypatch.setattr(M, "load_controls", lambda *a, **k: CTL)
    old = TODAY - dt.timedelta(days=40)
    claims = mini(old)
    reg = tmp_path / "claims.yaml"
    R.save(claims, reg)
    maps = tmp_path / "maps"
    maps.mkdir()
    world = {"tmp": tmp_path, "reg": reg, "maps": maps, "claims": claims}
    fs = [finding(c) for c in claims]
    fs[0] = finding(claims[0], reasons=["error"])
    code, out, _ = run(world, fs)
    assert code == A.EXIT_NEEDS_OWNER and out["version"]["action"] == "blocked"
    assert "expired" in out["version"]["why"] and any(x["id"] == "(map)" for x in out["needs_owner"])


def test_refuses_a_report_that_does_not_match_the_registry(world):
    rep = write_report(world["tmp"], world["reg"], [finding(c) for c in world["claims"]])
    world["claims"][0]["claim"] = "edited after the check"
    R.save(world["claims"], world["reg"])
    assert A.main(["--report", str(rep), "--registry", str(world["reg"]), "--maps-dir", str(world["maps"]),
                   "--reports-dir", str(world["tmp"] / "reports")]) == A.EXIT_SETUP


def test_dry_run_writes_nothing(world):
    before = world["reg"].read_bytes()
    code, _, _ = run(world, [finding(c) for c in world["claims"]], "--dry-run")
    assert code == A.EXIT_OK and world["reg"].read_bytes() == before
    assert not list((world["tmp"] / "reports").glob("*-auto.*"))


def test_a_new_review_clears_the_automated_record():
    c = mini(TODAY - dt.timedelta(days=10))[0]
    A.apply(c, [finding(c)], "unchanged", TODAY)
    assert R.auto_state(c) == "valid"
    review.record(c, "supported", "tester", TODAY)
    assert all(k not in c for k in R.AUTO_KEYS) and R.last_check(c) == (TODAY, "review")


def test_automated_record_is_void_once_the_claim_changes():
    c = mini(TODAY - dt.timedelta(days=10))[0]
    A.apply(c, [finding(c)], "unchanged", TODAY)
    c["claim"] = "something else"
    assert R.auto_state(c) == "void" and R.publishable(c)
