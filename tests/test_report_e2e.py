"""End to end over the run #0 fixture registry: statuses render, reasons are right, files are written."""

import json
from pathlib import Path

import pytest
import yaml

from drift import check as C
from drift import registry as R
from drift import report as REP
from drift.snapshot import sha256
from tests.conftest import reviewed

FIX = Path(__file__).parent / "fixtures" / "audit-run0.yaml"


@pytest.fixture
def fixture_registry(tmp_path):
    """Copy the fixture and fill in real hashes of the stored snapshots (kept as placeholders in the file),
    plus a review dated on the day the evidence was fetched (the fixture's own dates)."""
    claims = yaml.safe_load(FIX.read_text(encoding="utf-8"))["claims"]
    for c in claims:
        c["snapshot_hash"] = sha256(c["snapshot"])
        reviewed(c, when=str(c["fetched_at"]))
    reg = tmp_path / "claims.yaml"
    R.save(claims, reg)
    return reg


def serve_run0(http):
    http.add("https://fixtures.invalid/autogen", "<p>AutoGen is in maintenance mode: no new features</p>", "text/html")
    http.add("https://fixtures.invalid/windsurf", "<p>Devin Desktop (formerly Windsurf) is the new name</p>", "text/html")  # changed
    http.add("https://fixtures.invalid/sora", "<p>Sora was shut down on 2026-06-30</p>", "text/html")  # unchanged but stale
    http.add("https://api.github.com/repos/fixture-org/portkey-gateway", json.dumps({"archived": False}))
    http.add("https://api.github.com/repos/fixture-org/portkey-gateway/releases/latest",
             json.dumps({"tag_name": "v1.1.0", "published_at": "2026-10-01T00:00:00Z"}))  # version bump
    http.add("https://pypi.org/pypi/fixture-cleantool/json", json.dumps({
        "info": {"version": "3.0.0", "summary": "Clean"}, "releases": {"3.0.0": [{"upload_time": "2026-09-20T00:00:00"}]}}))


def only_report(out):
    (js,) = REP.list_reports(out)
    return js.with_suffix(".md").read_text(encoding="utf-8"), json.loads(js.read_text(encoding="utf-8")), js


def test_run0_fixture_report(http, fixture_registry, tmp_path):
    serve_run0(http)
    out = tmp_path / "reports"
    code = C.main(["--registry", str(fixture_registry), "--reports-dir", str(out), "--today", "2026-10-03", "--delay", "0"])
    assert code == C.EXIT_FLAGGED

    md, js, path = only_report(out)
    by_id = {f["id"]: f for f in js["findings"]}

    assert js["summary"]["checked"] == 5 and js["summary"]["flagged"] == 3 and js["summary"]["errors"] == 0
    assert by_id["L02-portkey"]["reasons"] == ["version_bump", "section_changed"]  # excerpt carries the version too
    assert by_id["L03-windsurf"]["reasons"] == ["section_changed"]
    assert by_id["L01-sora"]["reasons"] == ["stale"] and by_id["L01-sora"]["age_days"] == 63
    assert by_id["L03-autogen"]["reasons"] == [] and by_id["L10-clean"]["reasons"] == []

    # statuses render loudly enough for a human to notice
    for label in ("DEPRECATED", "RENAMED", "DEAD", "acquired"):
        assert label in md
    assert "| L02-portkey | Portkey | acquired | new version, page section changed | v1.0.0 | v1.1.0 |" in md
    assert "## Changed excerpts" in md and "Devin Desktop (formerly Windsurf) is the new name" in md
    assert "3 flagged" in md

    # F11: the run is named by its UTC timestamp and bound to the registry it read and the claim text
    assert path.stem.startswith("2026-10-03T") and path.stem.endswith("Z") and js["run_id"] == path.stem
    assert js["registry_sha256"] == R.file_sha256(fixture_registry)
    assert by_id["L03-windsurf"]["claim"] == "Windsurf was renamed Devin Desktop"
    assert js["digest"] == REP.content_digest(js)


def test_two_runs_same_day_do_not_overwrite(http, fixture_registry, tmp_path, monkeypatch):
    import datetime as dt

    serve_run0(http)
    out = tmp_path / "reports"
    stamps = iter([dt.datetime(2026, 10, 3, 8, 0, 0, tzinfo=dt.timezone.utc),
                   dt.datetime(2026, 10, 3, 9, 30, 5, tzinfo=dt.timezone.utc)])

    class FakeDT(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return next(stamps)

    monkeypatch.setattr(C.dt, "datetime", FakeDT)
    for _ in range(2):
        C.main(["--registry", str(fixture_registry), "--reports-dir", str(out), "--delay", "0"])
    assert [p.stem for p in REP.list_reports(out)] == ["2026-10-03T080000Z", "2026-10-03T093005Z"]


def test_vendor_text_cannot_break_report_markdown():
    """F10: a delimiter or tag in an excerpt stays inside its table cell."""
    import datetime as dt

    f = C.Finding(id="L01-x", layer=1, tool="X | injected", status="active", source_type="page_section",
                  source_url="https://x.invalid/", reasons=["section_changed"],
                  old_excerpt="a", new_excerpt="ok |\n## Fake heading\n<script>x</script> `code` [link](https://evil.invalid)")
    s = REP.summarize([f], dt.date(2026, 10, 3), "all")
    md = REP.render_markdown([f], s)
    import re

    table_rows = [ln for ln in md.splitlines() if ln.startswith("| L01-x")]
    assert len(table_rows) == 2  # flagged table (6 columns) and all-checked table (5 columns)
    assert sorted(len(re.findall(r"(?<!\\)\|", ln)) for ln in table_rows) == [6, 7]
    for ln in md.splitlines():
        assert not ln.startswith("## Fake") and "<script>" not in ln and not re.search(r"(?<!\\)\]\(", ln)


def test_dry_run_writes_nothing(http, fixture_registry, tmp_path):
    serve_run0(http)
    out = tmp_path / "reports"
    code = C.main(["--registry", str(fixture_registry), "--reports-dir", str(out), "--today", "2026-10-03", "--dry-run", "--delay", "0"])
    assert code == C.EXIT_FLAGGED and not out.exists()


def test_layer_filter_and_scoped_report_name(http, fixture_registry, tmp_path):
    serve_run0(http)
    out = tmp_path / "reports"
    code = C.main(["--registry", str(fixture_registry), "--reports-dir", str(out), "--today", "2026-10-03", "--layer", "10", "--delay", "0"])
    assert code == C.EXIT_CLEAN
    (p,) = REP.list_reports(out)
    assert p.stem.startswith("2026-10-03T") and p.stem.endswith("Z-layer-10")
    assert [u for u, _ in http.calls] == ["https://pypi.org/pypi/fixture-cleantool/json"]


def test_unreachable_source_is_error_exit(http, fixture_registry, tmp_path):
    serve_run0(http)
    http.fail("https://fixtures.invalid/sora", ConnectionError("down"))
    code = C.main(["--registry", str(fixture_registry), "--reports-dir", str(tmp_path / "r"), "--today", "2026-10-03", "--delay", "0"])
    assert code == C.EXIT_ERRORS
    _, js, _ = only_report(tmp_path / "r")
    sora = next(f for f in js["findings"] if f["id"] == "L01-sora")
    assert "error" in sora["reasons"] and "stale" in sora["reasons"]
