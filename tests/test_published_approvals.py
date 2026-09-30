"""Audit round 2, N1: a published "owner-approved" label must match an intact approval on the same review
event in the registry (same claim, PR reference and approval time, approval no later than the publication
date). A publication may under-report approvals recorded after it; it may never invent one."""

import datetime as dt
import json

import pytest

from drift import mapgen as M
from drift import registry as R
from drift import review
from tests.test_map import _published, mini_claims

URL = f"https://github.com/{R.REPOSITORY}/pull/7"


def approve(c: dict, when: str = "2026-09-28", ref: str = URL) -> dict:
    c.update(approved_by=R.OWNER_LOGIN, approved_at=when, approval_ref=ref)
    c["review_event_hash"] = R.review_event_hash(c)
    assert R.owner_approved(c)
    return c


def forge(maps, readme, md, **fields):
    """Edit the published map's first tool, then regenerate MAP.md from it (the auditor's probe)."""
    p = M.latest_map(maps)
    m = json.loads(p.read_text(encoding="utf-8"))
    m["layers"][0]["tools"][0].update(fields)
    p.write_text(M.map_json_text(m), encoding="utf-8")
    md.write_text(M.render_map_markdown(m), encoding="utf-8")
    readme.write_text("x\n" + M.render_readme_block(m) + "\ny\n", encoding="utf-8")
    return p


def verify(reg, maps, readme, md):
    return M.verify(maps, reg, readme, md, render=False)


def test_invented_approval_with_no_registry_record_fails_verify(tmp_path, monkeypatch):
    """The auditor's probe: the registry has no approval; the published map and MAP.md claim one."""
    claims = mini_claims(reviewed_on="2026-09-28")
    reg, maps, readme, md = _published(tmp_path, monkeypatch, claims)
    assert verify(reg, maps, readme, md)[0]
    forge(maps, readme, md, owner_approved=True, approved_at="2026-09-28", approval_ref=URL)
    ok, msgs = verify(reg, maps, readme, md)
    assert not ok and any("owner-approved" in x and "L01-t0" in x for x in msgs), msgs
    assert M.main(["verify", "--maps-dir", str(maps), "--registry", str(reg), "--readme", str(readme),
                   "--map-md", str(md), "--no-render"]) == 1


@pytest.mark.parametrize("field,value", [("approval_ref", f"https://github.com/{R.REPOSITORY}/pull/8"),
                                         ("approved_at", "2026-09-27")])
def test_published_approval_that_differs_from_the_registry_fails(tmp_path, monkeypatch, field, value):
    claims = mini_claims(reviewed_on="2026-09-27")
    approve(claims[0], when="2026-09-28")
    reg, maps, readme, md = _published(tmp_path, monkeypatch, claims)
    assert verify(reg, maps, readme, md)[0]  # the matching publication verifies
    forge(maps, readme, md, **{field: value})
    ok, msgs = verify(reg, maps, readme, md)
    assert not ok and any("owner-approved" in x for x in msgs), msgs


def test_published_approval_of_a_superseded_review_event_fails(tmp_path, monkeypatch):
    """A new review event carries no approval; the old publication's label no longer has a match."""
    claims = mini_claims(reviewed_on="2026-09-28")
    approve(claims[0])
    reg, maps, readme, md = _published(tmp_path, monkeypatch, claims)
    assert verify(reg, maps, readme, md)[0]
    claims[0]["claim"] = "Tool 1.0 is an actively offered model family"  # not map content
    review.record(claims[0], "supported", "claude-code", dt.date(2026, 9, 29))
    R.save(claims, reg)
    ok, msgs = verify(reg, maps, readme, md)
    assert not ok and any("owner-approved" in x for x in msgs), msgs


def test_published_approval_that_was_revoked_fails(tmp_path, monkeypatch):
    claims = mini_claims(reviewed_on="2026-09-28")
    approve(claims[0])
    reg, maps, readme, md = _published(tmp_path, monkeypatch, claims)
    for k in R.APPROVAL_KEYS:
        claims[0].pop(k)
    claims[0]["review_event_hash"] = R.review_event_hash(claims[0])  # a clean revocation: event still intact
    R.save(claims, reg)
    ok, msgs = verify(reg, maps, readme, md)
    assert not ok and any("owner-approved" in x for x in msgs), msgs


def test_published_approval_dated_after_the_publication_fails_check_and_verify(tmp_path, monkeypatch):
    claims = mini_claims(reviewed_on="2026-09-28")
    approve(claims[0], when="2026-10-02")  # recorded later than the v2026.09.28 publication
    reg, maps, readme, md = _published(tmp_path, monkeypatch, claims)
    p = M.latest_map(maps)
    assert json.loads(p.read_text(encoding="utf-8"))["layers"][0]["tools"][0]["owner_approved"] is True
    assert not M.check_expiry(p, dt.date(2026, 10, 2))[0]
    assert not verify(reg, maps, readme, md)[0]


def test_under_reporting_a_newer_approval_stays_valid(tmp_path, monkeypatch):
    claims = mini_claims(reviewed_on="2026-09-28")
    reg, maps, readme, md = _published(tmp_path, monkeypatch, claims)
    approve(claims[0], when="2026-10-02")
    R.save(claims, reg)
    ok, msgs = verify(reg, maps, readme, md)
    assert ok, msgs
