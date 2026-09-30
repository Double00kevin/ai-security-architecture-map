"""A01 (2026-09-29 audit): every check is labelled as what it was. Reviews are AI-assessed (`drift review`,
`reviewed_by` names the assessor); re-checks are automated (`drift auto`); "owner-approved" appears only
where a valid approval is recorded. Nothing calls a check a person's or a human review."""

import datetime as dt
import json
import re

import pytest

from drift import mapgen as M
from drift import registry as R
from tests.conftest import reviewed
from tests.test_map import CTL, mini_claims

URL = f"https://github.com/{R.REPOSITORY}/pull/9"

# Wording that says or implies a person reviewed the evidence.
MISLABEL = re.compile(r"a person's review|person's `supported` review|human review|read by a person|"
                      r"waits? for a person|needs? a person|review(?:ed)? by a person|record of the person|"
                      r"written only by a person|by a person via|a person reads|a person must review|"
                      r"a human reviews|routed to a human|human re-check|a human job|"
                      r"(?:reviewed|checked|read) by hand", re.I)
DOCS = ["README.md", "MAP.md", "CONTRIBUTING.md", "SECURITY.md", "docs/PUBLICATION.md", ".claude/CLAUDE.md",
        "DEFERRED.md", "registry/claims.yaml", "registry/governance.yaml", "CHANGELOG.md",
        "scripts/weekly-check.ps1", "render/render_map.py", "render/render_video.py"]
# Explicitly historical passages that may keep the old wording: (file, a substring of the line). Each must
# still match a line that carries a mislabel, so a stale entry fails too. Never add current wording here.
HISTORICAL = [
    ("CHANGELOG.md", '"human review" (MAP.md)'),  # the v2026.09.29.1 provenance correction quotes the old label
    ("CHANGELOG.md", "silently restore an invalidated human review"),  # the v2026.09.29 entry, as published
    ("CHANGELOG.md", "(historical wording; see the v2026.09.29.1 entry)"),  # the policy paragraph as it stood
]


def approve(c: dict, when: str = "2026-09-29") -> dict:  # never later than the v2026.09.29 test publication
    c.update(approved_by=R.OWNER_LOGIN, approved_at=when, approval_ref=URL)
    c["review_event_hash"] = R.review_event_hash(c)
    return c


@pytest.mark.parametrize("path", DOCS + [str(p.relative_to(R.ROOT)) for p in sorted((R.ROOT / "drift").rglob("*.py"))])
def test_no_public_text_calls_a_check_a_persons_review(path):
    allowed = [marker for f, marker in HISTORICAL if f == path]
    hits = [f"line {i}: {m.group(0)}" for i, line in enumerate((R.ROOT / path).read_text(encoding="utf-8").splitlines(), 1)
            for m in MISLABEL.finditer(line) if not any(marker in line for marker in allowed)]
    assert hits == [], f"{path}: {hits}"


@pytest.mark.parametrize("path,marker", HISTORICAL)
def test_every_historical_allowance_is_still_needed(path, marker):
    lines = [ln for ln in (R.ROOT / path).read_text(encoding="utf-8").splitlines() if marker in ln]
    assert lines and all(MISLABEL.search(ln) for ln in lines), f"stale allowance {marker!r} in {path}"


def test_governance_wording_keeps_every_review_record_unchanged():
    """The wording fix may not invent or re-record a governance review."""
    from drift import mapgen as M
    assert [(g["name"], g["reviewed_at"], g["reviewed_by"], g["review_due"]) for g in M.load_governance()] == [
        ("OWASP Top 10 for LLM Applications (2026)", "2026-09-27", "claude", "2026-10-27"),
        ("OWASP Top 10 for Agentic Applications", "2026-09-27", "claude", "2026-10-27"),
        ("NIST AI RMF", "2026-09-27", "claude", "2026-10-27"),
        ("ISO/IEC 42001", "2026-09-27", "claude", "2026-10-27"),
        ("MITRE ATLAS", "2026-09-27", "claude", "2026-10-27")]


def test_generated_map_md_says_what_each_check_was():
    claims = mini_claims(reviewed_on="2026-09-28")
    for c in claims:
        c["fetched_at"] = "2026-09-28"
        reviewed(c, when="2026-09-28", by="claude-code")
    approve(claims[0])
    m = M.build_map(claims, CTL, "v2026.09.29")
    M.validate_map(m, claims)
    md = M.render_map_markdown(m)
    assert "| Tool | Status | Owner | Receipt | Last check | Review |" in md
    assert "Human review" not in md and not MISLABEL.search(md)
    assert "AI-assessed review" in md and "`claude-code`" in md
    assert "1 of 69 reviews is owner-approved" in md
    lines = [ln for ln in md.splitlines() if ln.startswith("| Tool ")] and md.splitlines()
    row0 = next(ln for ln in lines if ln.startswith("| Tool 1.0 |"))
    row1 = next(ln for ln in lines if ln.startswith("| Tool 1.1 |"))
    assert "owner-approved 2026-09-29" in row0 and URL in row0
    assert "owner-approved" not in row1 and "AI-assessed (claude-code)" in row1


def test_map_json_labels_and_owner_approval_per_tool():
    claims = mini_claims(reviewed_on="2026-09-28")
    approve(claims[0])
    m = M.build_map(claims, CTL, "v2026.09.29")
    assert m["schema_version"] == M.SCHEMA_VERSION == 4
    tools = [t for layer in m["layers"] for t in layer["tools"]]
    assert {t["checked_by"] for t in tools} == {"review"}
    assert tools[0]["owner_approved"] is True and tools[0]["approval_ref"] == URL and tools[0]["approved_at"] == "2026-09-29"
    assert all(t["owner_approved"] is False and t["approval_ref"] is None for t in tools[1:])
    assert all(t["reviewed_by"] == "tester" for t in tools)


def test_owner_approved_needs_all_three_fields_and_a_valid_event_digest():
    c = approve(reviewed(mini_claims()[0], when="2026-09-27"))
    assert R.owner_approved(c)
    broken = dict(c, approved_at="2026-10-03")  # edited without a new event digest
    assert not R.owner_approved(broken)
    m = M.build_map([broken if x["id"] == c["id"] else x for x in mini_claims()], CTL, "v2026.09.27")
    assert m["layers"][0]["tools"][0]["owner_approved"] is False


@pytest.mark.parametrize("label,schema,ok", [("person", 3, True), ("review", 3, False), ("person", 4, False),
                                             ("review", 4, True), ("auto", 4, True), ("owner", 4, False)])
def test_checked_by_vocabulary_per_schema(label, schema, ok):
    m = M.build_map(mini_claims(), CTL, "v2026.09.27")
    m["schema_version"] = schema
    for layer in m["layers"]:
        for t in layer["tools"]:
            t["checked_by"] = label
            if label == "auto":
                t["checked_at"] = t["reviewed_at"]
    if ok:
        M.validate_publication_dates(m)
    else:
        with pytest.raises(M.MapError):
            M.validate_publication_dates(m)


def test_schema_4_rejects_an_owner_approval_flag_without_a_reference():
    m = M.build_map(mini_claims(), CTL, "v2026.09.27")
    m["layers"][0]["tools"][0]["owner_approved"] = True
    with pytest.raises(M.MapError, match="owner approval"):
        M.validate_publication_dates(m)


def test_last_check_is_labelled_review_or_auto():
    c = reviewed(mini_claims()[0], when="2026-09-27")
    assert R.last_check(c) == (dt.date(2026, 9, 27), "review")
    assert R.REVIEW_MAX_DAYS == 180 and not hasattr(R, "HUMAN_REVIEW_MAX_DAYS")


def test_committed_map_json_uses_the_current_vocabulary():
    m = json.loads(M.latest_map().read_text(encoding="utf-8"))
    tools = [t for layer in m["layers"] for t in layer["tools"]]
    assert {t["checked_by"] for t in tools} <= {"review", "auto"}
    assert all(t["reviewed_by"] in ("claude", "claude-code") for t in tools)
    assert not any(t["owner_approved"] for t in tools)  # no approval was backfilled
