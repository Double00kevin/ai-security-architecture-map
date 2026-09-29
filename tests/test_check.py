"""Fault injection: a version bump, a changed section, a lifecycle signal and an overdue review must each be flagged."""

import datetime as dt
import json

from drift import check as C
from drift.sources import Evidence
from drift.snapshot import sha256
from tests.conftest import claim, reviewed

TODAY = dt.date(2026, 10, 3)


def stored(when="2026-09-27", **kw):
    base = {"snapshot": "pypi example 1.0.0", "snapshot_hash": sha256("pypi example 1.0.0"),
            "last_version": "1.0.0", "fetched_at": "2026-09-27"}
    return reviewed(claim(**{**base, **kw}), when=when)


def test_clean_claim_not_flagged():
    f = C.compare(stored(), Evidence("1.0.0", "pypi example 1.0.0"), TODAY)
    assert not f.flagged and f.reasons == []


def test_version_bump_flagged():
    f = C.compare(stored(), Evidence("1.1.0", "pypi example 1.1.0"), TODAY)
    assert "version_bump" in f.reasons and f.old_version == "1.0.0" and f.new_version == "1.1.0"


def test_section_change_flagged_without_version():
    c = stored(source_type="page_section", locator="x", last_version=None, snapshot="Flagship: GPT-5",
               snapshot_hash=sha256("Flagship: GPT-5"))
    f = C.compare(c, Evidence(None, "Flagship: GPT-6"), TODAY)
    assert f.reasons == ["section_changed"]


def test_lifecycle_signal_is_its_own_reason():
    f = C.compare(stored(), Evidence("1.0.0", "pypi example 1.0.0 | LIFECYCLE: pypi 1.0.0 is yanked",
                                     ("pypi 1.0.0 is yanked",)), TODAY)
    assert "lifecycle" in f.reasons and f.lifecycle == ["pypi 1.0.0 is yanked"]


def test_31_days_since_review_is_stale_30_is_not():
    ev = Evidence("1.0.0", "pypi example 1.0.0")
    assert "stale" in C.compare(stored(when="2026-09-02"), ev, TODAY).reasons  # 31 days
    assert "stale" not in C.compare(stored(when="2026-09-03"), ev, TODAY).reasons  # 30 days


def test_never_reviewed_is_stale_even_if_freshly_fetched():
    """fetched_at is not a review: a claim fetched today but never reviewed is still due for review."""
    c = claim(snapshot="pypi example 1.0.0", snapshot_hash=sha256("pypi example 1.0.0"), last_version="1.0.0",
              fetched_at=TODAY.isoformat())
    f = C.compare(c, Evidence("1.0.0", "pypi example 1.0.0"), TODAY)
    assert "stale" in f.reasons and f.age_days is None and f.review_state == "missing"


def test_void_review_is_stale():
    c = stored()
    c["claim"] = "Example is active and wonderful"  # edited after review: the review no longer matches
    f = C.compare(c, Evidence("1.0.0", "pypi example 1.0.0"), TODAY)
    assert "stale" in f.reasons and f.review_state == "void"


def test_every_receipt_is_checked_and_stale_is_reported_once(http):
    c = stored(sources=[{"source_type": "npm", "source_url": "https://www.npmjs.com/package/example",
                         "snapshot": "npm example 2.0.0: x", "snapshot_hash": sha256("npm example 2.0.0: x"),
                         "last_version": "2.0.0", "supports": ["ownership"]}])
    http.add("https://pypi.org/pypi/example/json", json.dumps({"info": {"version": "1.0.0", "summary": ""},
                                                             "releases": {}}))
    http.add("https://registry.npmjs.org/example/latest", json.dumps({"version": "2.0.1", "description": "x"}))
    from drift import registry
    fs = C.check_claims([c], registry.allowlist([c]), dt.date(2026, 12, 1), delay=0, log=lambda *_: None)
    assert [f.key for f in fs] == ["L01-example", "L01-example#1"]
    assert fs[1].reasons == ["version_bump", "section_changed"]
    assert sum("stale" in f.reasons for f in fs) == 1


def test_fetch_error_becomes_error_finding(http):
    c = stored()
    http.fail("https://pypi.org/pypi/example/json", ConnectionError("boom"))
    (f,) = C.check_claims([c], frozenset({"https://pypi.org/pypi/example/json"}), TODAY, delay=0, log=lambda *_: None)
    assert f.reasons == ["error"] and "ConnectionError" in f.error


def test_check_never_writes_registry(http, tmp_path):
    """`drift check` is read-only on the registry even when everything is flagged."""
    import yaml

    from drift import registry as R

    reg = tmp_path / "claims.yaml"
    R.save([stored()], reg)
    before = reg.read_bytes()
    http.add("https://pypi.org/pypi/example/json", json.dumps({"info": {"version": "9.9.9", "summary": ""}, "releases": {}}))
    code = C.main(["--registry", str(reg), "--reports-dir", str(tmp_path / "r"), "--today", "2026-11-30", "--delay", "0"])
    assert code == C.EXIT_FLAGGED
    assert reg.read_bytes() == before
    assert yaml.safe_load(reg.read_text(encoding="utf-8"))["claims"][0]["last_version"] == "1.0.0"


# ---- R5 (PR #5 review): an unchanged source must not make an unresolved review look clean ----

def test_unsupported_review_is_flagged_even_when_the_source_is_unchanged():
    c = reviewed(claim(snapshot="Workforce AI Security", snapshot_hash=sha256("Workforce AI Security"),
                       source_type="page_section", locator="x", assertions=["availability", "ownership"],
                       supports=["capability"]), when="2026-10-01", outcome="unsupported")
    f = C.compare(c, Evidence(None, "Workforce AI Security"), TODAY)
    assert f.flagged and f.reasons == ["unresolved_review"]
    assert f.review_outcome == "unsupported" and f.unsupported_assertions == ["availability", "ownership"]


def test_partial_candidate_is_flagged_and_labelled_as_candidate():
    c = stored(when="2026-10-01", on_map=False)
    reviewed(c, when="2026-10-01", outcome="partial")  # the outcome is part of the review event
    f = C.compare(c, Evidence("1.0.0", "pypi example 1.0.0"), TODAY)
    assert f.flagged and "unresolved_review" in f.reasons and not f.on_map


def test_edited_excerpt_is_an_integrity_finding():
    c = stored(when="2026-10-01")
    c["snapshot"] = "pypi example 9.9.9"  # digest left alone
    f = C.compare(c, Evidence("1.0.0", "pypi example 1.0.0"), TODAY)
    assert "integrity" in f.reasons and f.integrity


def test_report_shows_unresolved_outcome_and_missing_assertions(tmp_path):
    from drift import report
    c = reviewed(claim(snapshot="x", snapshot_hash=sha256("x"), assertions=["ownership"], supports=["capability"]),
                 when="2026-10-01", outcome="unsupported")
    f = C.compare(c, Evidence(None, "x"), TODAY)
    s = report.summarize([f], TODAY, "all")
    reg = tmp_path / "claims.yaml"
    reg.write_text("claims: []\n", encoding="utf-8")
    md = report.render_markdown([f], s, report.run_meta(dt.datetime(2026, 10, 3, 8, tzinfo=dt.timezone.utc), "all", reg))
    assert "REVIEW NOT SUPPORTED" in md and "outcome unsupported" in md and "no receipt for ownership" in md


def test_a_reviewed_lifecycle_signal_does_not_reflag_every_week():
    sig = 'release v2 notes mention "deprecat": ...old flag removed'
    excerpt = f"org/tool latest release v2 | LIFECYCLE: {sig}"
    c = stored(when="2026-10-01", source_type="github_release", source_url="https://github.com/org/tool",
               snapshot=excerpt, snapshot_hash=sha256(excerpt), last_version="v2")
    ev = Evidence("v2", excerpt, lifecycle=(sig,))
    assert C.compare(c, ev, TODAY).reasons == []
    ev2 = Evidence("v2", excerpt + " | LIFECYCLE: repository archived", lifecycle=(sig, "repository archived"))
    assert "lifecycle" in C.compare(c, ev2, TODAY).reasons
