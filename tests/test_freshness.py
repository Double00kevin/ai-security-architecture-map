"""A05 (2026-09-29 audit): a time-based claim is not renewed once the observed timestamp is too old."""

import datetime as dt

import pytest

from drift import auto as A
from drift import check as C
from drift import registry as R
from drift.sources import Evidence
from tests.conftest import claim, reviewed


def qwen() -> dict:
    (c,) = [c for c in R.load() if c["id"] == "L01-qwen"]
    return c


def unchanged(c: dict) -> list[dict]:
    return [{"id": c["id"], "receipt": 0, "reasons": [], "old_hash": c["snapshot_hash"],
             "new_hash": c["snapshot_hash"], "new_excerpt": c["snapshot"]}]


def test_qwen_receipt_carries_a_30_day_freshness_rule():
    assert qwen()["freshness"] == {"field": "lastModified", "max_age_days": 30}


@pytest.mark.parametrize("today,ok", [(dt.date(2026, 10, 1), True), (dt.date(2026, 11, 1), False)])
def test_unchanged_qwen_timestamp_passes_in_october_and_fails_in_november(today, ok):
    c = qwen()
    f = C.compare(c, Evidence(None, c["snapshot"]), today)
    assert ("freshness" in f.reasons) is not ok
    renew, why = A.decide(c, [C.finding_dict(f)], today)
    assert renew is ok, why
    if not ok:
        assert "lastModified 2026-09-27 is 35 days old (limit 30)" in why
        assert any("lastModified" in n for n in f.notes)


def test_freshness_rule_is_not_claim_content():
    """Documented choice: the rule is a check setting, so adding it did not void the Qwen review."""
    c = qwen()
    assert R.review_state(c) == "valid" and R.publishable(c) == []
    before = (R.review_hash(c), R.claim_hash(c))
    c["freshness"] = {"field": "lastModified", "max_age_days": 7}
    assert (R.review_hash(c), R.claim_hash(c)) == before


def test_missing_timestamp_is_a_violation():
    r = {"freshness": {"field": "lastModified", "max_age_days": 30}}
    assert "no lastModified" in R.freshness_problem(r, "nothing here", dt.date(2026, 10, 1))
    assert R.freshness_problem({}, "anything", dt.date(2026, 10, 1)) is None


@pytest.mark.parametrize("rule", [{"field": "x"}, {"max_age_days": 3}, {"field": "x", "max_age_days": 0},
                                  {"field": "a b", "max_age_days": 3}, "30 days"])
def test_malformed_freshness_rule_is_a_registry_error(rule):
    with pytest.raises(R.RegistryError, match="freshness"):
        R.validate([claim(freshness=rule)])


def test_triage_routes_a_freshness_finding_to_the_owner_without_a_model_call():
    from drift import triage as T
    c = reviewed(claim(source_type="page_section", locator="x", fetched_at="2026-09-28",
                       snapshot='"lastModified":"2026-09-01T00:00:00Z"',
                       snapshot_hash=R.excerpt_sha256('"lastModified":"2026-09-01T00:00:00Z"'),
                       freshness={"field": "lastModified", "max_age_days": 30}))
    f = C.finding_dict(C.compare(c, Evidence(None, c["snapshot"]), dt.date(2026, 10, 3)))
    assert f["reasons"] == ["freshness"]

    def boom(*a, **k):
        raise AssertionError("no model call for a freshness finding")
    t = T.triage_findings([f], {c["id"]: c}, None, budget_usd=1.0, max_calls=5,
                          call=boom, log=lambda *a: None)
    (r,) = t["results"]
    assert r["verdict"] == "needs_human" and "freshness" in r["reason"]
