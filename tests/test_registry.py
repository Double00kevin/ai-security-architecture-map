"""The real registry keeps its shape; the loader rejects malformed records."""

import pytest

from drift import registry as R
from tests.conftest import claim, reviewed


def test_real_registry_has_62_on_map_claims_with_map_layer_counts():
    claims = R.load()
    on_map = R.on_map(claims)
    assert len(on_map) == 69
    assert R.layer_counts(on_map) == R.LAYER_COUNTS == [10, 5, 6, 5, 5, 7, 5, 5, 5, 6, 5, 5]
    assert len(claims) >= 62  # verified candidates may sit alongside, off-map


def test_real_registry_every_claim_has_evidence():
    for c in R.load():
        assert c["source_url"].startswith("https://"), c["id"]
        assert c["snapshot"] and c["snapshot_hash"].startswith("sha256:"), c["id"]
        assert c["fetched_at"], c["id"]
        assert "last_checked" not in c and "checked_by" not in c, c["id"]


def test_real_registry_has_no_lan_details():
    import re
    text = R.REGISTRY.read_text(encoding="utf-8")
    # four octets required: "pinecone 10.0.0" is a version, not an address
    assert not re.search(r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b", text)
    assert "C:\\" not in text and "/home/" not in text and "/Users/" not in text


@pytest.mark.parametrize("bad,msg", [
    ({"status": "gone"}, "bad status"),
    ({"source_type": "ftp"}, "bad source_type"),
    ({"source_url": "http://pypi.org/project/x/"}, "must be https"),
    ({"source_type": "page_section", "locator": None}, "needs a locator"),
    ({"on_map": "yes"}, "on_map must be"),
    ({"layer": 99, "id": "L99-example"}, "layer must be an integer 1..12"),
    ({"layer": 0, "id": "L00-example"}, "layer must be an integer 1..12"),
    ({"layer": "3"}, "layer must be an integer"),
    ({"id": "L02-example"}, "id must look like L01-"),
    ({"last_checked": "2020-01-01"}, "legacy field"),
    ({"assertions": ["vibes"]}, "unknown assertions"),
    ({"supports": ["vibes"]}, "unknown supports"),
    ({"owner": "Acme"}, "'ownership' is not in assertions"),
    ({"review_outcome": "supported"}, "incomplete review record"),
    ({"redirect_to": "http://pypi.org/project/x/"}, "redirect_to must be https"),
])
def test_validate_rejects(bad, msg):
    with pytest.raises(R.RegistryError, match=msg):
        R.validate([claim(**bad)])


def test_validate_rejects_duplicate_ids():
    with pytest.raises(R.RegistryError, match="duplicate"):
        R.validate([claim(), claim()])


def test_validate_rejects_duplicate_layer_tool_on_map():
    with pytest.raises(R.RegistryError, match="duplicate on-map tool"):
        R.validate([claim(), claim(id="L01-example-2")])
    R.validate([claim(), claim(id="L01-example-2", on_map=False)])  # a candidate may shadow a map tool


def test_review_hash_voids_on_any_reviewed_change():
    """Acceptance 1: a review is bound to what was reviewed and voided when claim, source, evidence or owner change."""
    base = reviewed(claim(assertions=["availability", "ownership"], supports=["availability", "ownership"], owner="Acme"))
    assert R.review_state(base) == "valid" and R.validate([base]) == []
    for field, value in [("claim", "Example is active and great"), ("source_url", "https://pypi.org/project/other/"),
                         ("snapshot_hash", "sha256:" + "0" * 64), ("owner", "Other Corp"), ("status", "dead"),
                         ("supports", ["availability"]), ("assertions", ["availability"]), ("tool", "Renamed")]:
        c = dict(base, **{field: value})
        if field == "assertions":
            c["owner"] = None  # keep the record valid; only the review should break
        assert R.review_state(c) == "void", field
        if field not in ("owner",):
            assert c["id"] in R.validate([c]), field


def test_review_hash_voids_when_an_extra_source_changes():
    extra = {"source_type": "page_section", "source_url": "https://vendor.example/blog", "locator": "x",
             "snapshot": "joined", "snapshot_hash": R.excerpt_sha256("joined"), "supports": ["ownership"]}
    c = reviewed(claim(assertions=["availability"], sources=[extra]))
    assert R.review_state(c) == "valid"
    # new evidence, correctly re-taken (excerpt and digest both change): the review no longer covers it
    c["sources"][0].update(snapshot="joined BigCo", snapshot_hash=R.excerpt_sha256("joined BigCo"))
    assert R.review_state(c) == "void"


def test_fetched_at_alone_is_never_a_review():
    c = claim(snapshot="x", snapshot_hash=R.excerpt_sha256("x"), fetched_at="2026-09-28",
              assertions=["availability"], supports=["availability"])
    assert R.review_state(c) == "missing" and "review missing" in "; ".join(R.publishable(c))


def test_publishable_needs_every_assertion_supported_by_a_receipt_with_evidence():
    c = reviewed(claim(assertions=["availability", "ownership"], supports=["availability"]))
    assert R.review_state(c) == "valid"
    assert any("no supporting receipt for: ownership" in w for w in R.publishable(c))
    c2 = reviewed(claim(assertions=["availability", "ownership"], supports=["availability"],
                        sources=[{"source_type": "npm", "source_url": "https://www.npmjs.com/package/example",
                                  "supports": ["ownership"]}]))  # supports ownership, but no snapshot yet
    why = "; ".join(R.publishable(c2))
    assert "receipt 1" in why and "no supporting receipt for: ownership" in why


def test_ownership_event_must_be_evidenced_by_one_of_the_receipts():
    ev = {"kind": "acquisition_completed", "counterparty": "BigCo", "date": "2026-01-16",
          "source_url": "https://vendor.example/blog", "note": ""}
    with pytest.raises(R.RegistryError, match="must be one of the claim's receipts"):
        R.validate([claim(owner="BigCo", assertions=["ownership"], ownership_event=ev)])
    ok = claim(owner="BigCo", assertions=["ownership"], ownership_event=ev,
               sources=[{"source_type": "page_section", "source_url": "https://vendor.example/blog", "locator": "x",
                         "supports": ["ownership"]}])
    R.validate([ok])
    with pytest.raises(R.RegistryError, match="kind"):
        R.validate([dict(ok, ownership_event=dict(ev, kind="bought"))])


def test_review_command_refuses_supported_without_evidence(tmp_path):
    from drift import review

    reg = tmp_path / "claims.yaml"
    R.save([claim(assertions=["availability"], supports=["availability"])], reg)
    assert review.main(["--id", "L01-example", "--outcome", "supported", "--by", "tester", "--registry", str(reg)]) == 1
    assert review.main(["--id", "L01-example", "--outcome", "unsupported", "--by", "tester", "--registry", str(reg)]) == 0
    (c,) = R.load(reg)
    assert c["review_outcome"] == "unsupported" and R.review_state(c) == "valid"


def test_snapshot_never_writes_a_review(http, tmp_path):
    import json

    from drift import snapshot

    reg = tmp_path / "claims.yaml"
    R.save([claim(assertions=["availability"], supports=["availability"])], reg)
    http.add("https://pypi.org/pypi/example/json", json.dumps({"info": {"version": "1.0.0", "summary": "x"}, "releases": {}}))
    assert snapshot.main(["--all", "--registry", str(reg), "--delay", "0"]) == 0
    (c,) = R.load(reg)
    assert c["snapshot"] and c["fetched_at"] and R.review_state(c) == "missing"
    assert not any(c.get(k) for k in R.REVIEW_KEYS)


def test_snapshot_of_changed_evidence_voids_the_review(http, tmp_path, capsys):
    import json

    from drift import snapshot

    reg = tmp_path / "claims.yaml"
    R.save([reviewed(claim())], reg)
    http.add("https://pypi.org/pypi/example/json", json.dumps({"info": {"version": "2.0.0", "summary": "x"}, "releases": {}}))
    snapshot.main(["--all", "--registry", str(reg), "--delay", "0"])
    (c,) = R.load(reg)
    assert R.review_state(c) == "void" and "VOIDED" in capsys.readouterr().out


# ---- R2 (PR #5 review): a stored digest is recomputed, never trusted ----

def _edited_excerpt(c: dict, index: int = 0) -> dict:
    """What the review found: the excerpt text changed, the stored digest and review fields did not."""
    if index == 0:
        c["snapshot"] = c["snapshot"] + " (edited by hand)"
    else:
        c["sources"][index - 1]["snapshot"] += " (edited by hand)"
    return c


def test_edited_primary_excerpt_with_stale_digest_voids_the_review_and_blocks_publication():
    c = reviewed(claim())
    assert R.review_state(c) == "valid" and R.publishable(c) == []
    _edited_excerpt(c)
    assert R.review_state(c) == "void"
    assert c["id"] in R.validate([c])
    why = "; ".join(R.publishable(c))
    assert "snapshot_hash does not match its excerpt" in why and "no supporting receipt for: availability" in why


def test_edited_extra_receipt_excerpt_with_stale_digest_voids_the_review():
    extra = {"source_type": "page_section", "source_url": "https://vendor.example/blog", "locator": "x",
             "snapshot": "BigCo acquired Example", "snapshot_hash": R.excerpt_sha256("BigCo acquired Example"),
             "supports": ["ownership"]}
    c = reviewed(claim(assertions=["availability", "ownership"], supports=["availability"], owner="BigCo",
                       sources=[extra]))
    assert R.review_state(c) == "valid" and R.publishable(c) == []
    _edited_excerpt(c, 1)
    assert R.review_state(c) == "void"
    assert any("receipt 1" in w and "does not match" in w for w in R.publishable(c))


def test_malformed_digest_is_a_registry_error():
    for bad in ("sha256:abc", "md5:" + "0" * 32, "sha256:" + "G" * 64):
        with pytest.raises(R.RegistryError, match="snapshot_hash must look like"):
            R.validate([claim(snapshot="x", snapshot_hash=bad)])


def test_review_command_refuses_evidence_that_does_not_match_its_digest():
    import datetime as dt
    from drift import review
    c = reviewed(claim())
    _edited_excerpt(c)
    for outcome in ("supported", "partial", "unsupported"):
        with pytest.raises(R.RegistryError, match="does not match its digest"):
            review.record(c, outcome, "tester", dt.date(2026, 9, 28))


def test_every_committed_receipt_digest_matches_its_excerpt():
    claims = R.load()
    bad = [(c["id"], p) for c in claims for p in R.integrity_problems(c)]
    assert bad == []


# ---- A03 (2026-09-29 audit): the review event binds outcome, assessor, date and fetch dates ----

import datetime as _dt  # noqa: E402

from drift import auto as _A  # noqa: E402
from drift import review as _review  # noqa: E402


def _valid_claim():
    c = reviewed(claim(fetched_at="2026-09-27"), when="2026-09-28")
    assert R.review_state(c) == "valid" and R.publishable(c) == []
    return c


EVENT_EDITS = [("reviewed_by", "someone-else"), ("reviewed_at", "2026-09-29"), ("review_outcome", "partial"),
               ("fetched_at", "2026-09-28")]


@pytest.mark.parametrize("field,value", EVENT_EDITS)
def test_editing_review_metadata_voids_the_event(field, value):
    c = _valid_claim()
    c[field] = value
    assert R.review_state(c) == "void", field
    assert R.publishable(c), field
    assert c["id"] in R.validate([c])
    assert R.last_check(c) == (None, None)


def test_editing_a_secondary_receipt_fetch_date_voids_the_event():
    extra = {"source_type": "pypi", "source_url": "https://pypi.org/project/other/", "snapshot": "x",
             "snapshot_hash": R.excerpt_sha256("x"), "fetched_at": "2026-09-27", "supports": ["availability"]}
    c = reviewed(claim(fetched_at="2026-09-27", sources=[extra]), when="2026-09-28")
    assert R.review_state(c) == "valid"
    c["sources"][0]["fetched_at"] = "2026-09-28"
    assert R.review_state(c) == "void" and R.publishable(c)


@pytest.mark.parametrize("field,value", EVENT_EDITS[:3] + [("auto_checked_at", "2026-10-30")])
def test_editing_review_metadata_also_voids_an_automated_re_check(field, value):
    c = _valid_claim()
    _A.apply(c, [{"id": c["id"], "receipt": 0, "reasons": [], "old_hash": c["snapshot_hash"],
                  "new_hash": c["snapshot_hash"], "new_excerpt": c["snapshot"]}], "unchanged", _dt.date(2026, 10, 3))
    assert R.auto_state(c) == "valid" and R.publishable(c) == []
    c[field] = value
    assert R.auto_state(c) == "void" and R.publishable(c), field


def test_a_new_review_event_restores_publishability():
    c = _valid_claim()
    c["reviewed_by"] = "someone-else"
    assert R.publishable(c)
    _review.record(c, "supported", "claude-code", _dt.date(2026, 9, 29))
    assert R.review_state(c) == "valid" and R.publishable(c) == []
    assert c["review_fetched_at"] == ["2026-09-27"]


def test_review_record_is_complete_or_rejected():
    c = _valid_claim()
    del c["review_event_hash"]
    with pytest.raises(R.RegistryError, match="incomplete review record"):
        R.validate([c])


# ---- A03: the one-time migration of existing review records ----

from drift import migrate as _migrate  # noqa: E402


def _old_format(c: dict) -> dict:
    """A review record as written before the event digest existed (five keys)."""
    for k in ("review_fetched_at", "review_event_hash"):
        c.pop(k)
    return c


def test_migration_binds_existing_reviews_without_changing_anything_else():
    claims = [_old_format(_valid_claim()), claim(id="L01-unreviewed", tool="Other")]
    before = [dict(c) for c in claims]
    n = _migrate.add_review_events(claims)
    assert n == 1
    c = claims[0]
    assert {k: v for k, v in c.items() if k not in ("review_fetched_at", "review_event_hash")} == before[0]
    assert claims[1] == before[1]
    assert c["review_fetched_at"] == ["2026-09-27"] and R.review_state(c) == "valid"
    assert R.last_check(c) == (_dt.date(2026, 9, 28), R.last_check(c)[1])
    R.validate(claims)


def test_migration_refuses_a_void_old_review_and_writes_nothing():
    good, bad = _old_format(_valid_claim()), _old_format(_valid_claim())
    bad.update(id="L01-edited", tool="Edited", claim="edited after the review")
    snapshot = [dict(good), dict(bad)]
    with pytest.raises(R.RegistryError, match="L01-edited"):
        _migrate.add_review_events([good, bad])
    assert [good, bad] == snapshot


def test_migration_refuses_a_registry_that_is_already_migrated():
    with pytest.raises(R.RegistryError, match="already"):
        _migrate.add_review_events([_valid_claim()])


def test_migration_cannot_extend_review_age(tmp_path):
    """No date is an input: the review date and every check date stay exactly as they were."""
    import inspect
    import yaml
    assert list(inspect.signature(_migrate.add_review_events).parameters) == ["claims"]
    reg = tmp_path / "claims.yaml"
    old = [_old_format(_valid_claim())]
    reg.write_text(yaml.safe_dump({"claims": old}, sort_keys=False), encoding="utf-8")
    assert _migrate.main(["review-events", "--registry", str(reg)]) == 0
    (c,) = R.load(reg)
    assert c["reviewed_at"] == "2026-09-28" and c["fetched_at"] == "2026-09-27"
    assert R.last_check(c)[0] == _dt.date(2026, 9, 28)
    assert _migrate.main(["review-events", "--registry", str(reg)]) == 1  # second run refuses


def test_every_committed_review_record_has_a_valid_event():
    for c in R.load():
        assert c.get("review_event_hash") and R.review_event_intact(c), c["id"]


# ---- A04 (2026-09-29 audit): a review must rest on a fresh fetch ----

def test_review_of_a_2020_fetch_is_refused_at_review_time():
    c = claim(snapshot="x", snapshot_hash=R.excerpt_sha256("x"), fetched_at="2020-01-01",
              assertions=["availability"], supports=["availability"])
    for outcome in R.REVIEW_OUTCOMES:
        with pytest.raises(R.RegistryError, match="fetched 2020-01-01"):
            _review.record(c, outcome, "claude-code", _dt.date(2026, 9, 29))
    assert R.review_state(c) == "missing"


def test_review_of_a_2020_fetch_is_refused_at_publish_time(tmp_path):
    """The same record written by hand (hashes recomputed) cannot publish or be carried forward."""
    c = reviewed(claim(snapshot="x", snapshot_hash=R.excerpt_sha256("x"), fetched_at="2020-01-01"), when="2026-09-29")
    assert R.review_state(c) == "valid"
    assert any("fetched 2020-01-01" in w for w in R.publishable(c)), R.publishable(c)
    ok, why = _A.decide(c, [{"id": c["id"], "receipt": 0, "reasons": [], "old_hash": c["snapshot_hash"],
                              "new_hash": c["snapshot_hash"], "new_excerpt": c["snapshot"]}], _dt.date(2026, 9, 30))
    assert not ok and "fetched 2020-01-01" in why


@pytest.mark.parametrize("fetched,ok", [("2026-09-22", True), ("2026-09-21", False), ("2026-09-29", True),
                                        ("2026-09-30", False)])
def test_fetch_window_is_seven_days_before_the_review_and_never_after(fetched, ok):
    assert R.REVIEW_FETCH_MAX_DAYS == 7
    c = claim(snapshot="x", snapshot_hash=R.excerpt_sha256("x"), fetched_at=fetched,
              assertions=["availability"], supports=["availability"])
    if ok:
        _review.record(c, "supported", "claude-code", _dt.date(2026, 9, 29))
        assert R.publishable(c) == []
    else:
        with pytest.raises(R.RegistryError, match="fetched"):
            _review.record(c, "supported", "claude-code", _dt.date(2026, 9, 29))
        assert R.publishable(reviewed(c, when="2026-09-29"))
