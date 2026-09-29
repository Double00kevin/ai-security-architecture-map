"""Each source handler turns a canned response into Evidence(version, excerpt)."""

import json

import pytest

from drift.sources import SourceError, evidence_for
from tests.conftest import claim


def gh(**kw):
    return claim(**{"source_type": "github_release", "source_url": "https://github.com/o/r", **kw})


ALLOW_GH = frozenset({"https://github.com/o/r", "https://api.github.com/repos/o/r", "https://api.github.com/repos/o/r/releases/latest",
                      "https://api.github.com/repos/o/r/tags?per_page=1", "https://api.github.com/repos/o/r/tags?per_page=100"})


@pytest.fixture
def repo(http):
    http.add("https://api.github.com/repos/o/r", json.dumps({"full_name": "o/r", "archived": False}))
    return http


def test_github_release(repo, http):
    http.add("https://api.github.com/repos/o/r/releases/latest", json.dumps({"tag_name": "v1.2.3", "published_at": "2026-09-01T00:00:00Z"}))
    ev = evidence_for(gh(), ALLOW_GH)
    assert ev.version == "v1.2.3" and "v1.2.3" in ev.excerpt


def test_github_release_404_falls_back_to_tags(repo, http):
    http.add("https://api.github.com/repos/o/r/releases/latest", b"{}", status=404)
    http.add("https://api.github.com/repos/o/r/tags?per_page=1", json.dumps([{"name": "v0.8.6"}]))
    assert evidence_for(gh(), ALLOW_GH).version == "v0.8.6"


def test_github_tag_pattern_picks_first_matching(repo, http):
    tags = [{"name": "browser-0.1.24"}, {"name": "2026.09.0"}, {"name": "2026.08.1"}]
    http.add("https://api.github.com/repos/o/r/tags?per_page=100", json.dumps(tags))
    ev = evidence_for(gh(source_type="github_tag", locator=r"\d{4}\.\d\d\.\d+"), ALLOW_GH)
    assert ev.version == "2026.09.0"


def test_github_no_tags_is_source_error(repo, http):
    http.add("https://api.github.com/repos/o/r/tags?per_page=1", b"[]")
    with pytest.raises(SourceError):
        evidence_for(gh(source_type="github_tag"), ALLOW_GH)


def test_pypi(http):
    http.add("https://pypi.org/pypi/example/json", json.dumps({
        "info": {"version": "2.0.0", "summary": "Example lib"},
        "releases": {"2.0.0": [{"upload_time": "2026-09-20T10:00:00"}]}}))
    ev = evidence_for(claim(), frozenset({"https://pypi.org/pypi/example/json"}))
    assert ev.version == "2.0.0" and "2026-09-20" in ev.excerpt and "Example lib" in ev.excerpt


def test_npm_uses_latest_document_only(http):
    http.add("https://registry.npmjs.org/n8n/latest", json.dumps({"version": "2.40.7", "description": "n8n"}))
    ev = evidence_for(claim(source_type="npm", source_url="https://www.npmjs.com/package/n8n"),
                      frozenset({"https://registry.npmjs.org/n8n/latest"}))
    assert ev.version == "2.40.7"
    assert http.calls[0][0].endswith("/latest")


RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Blog</title>
<item><title>Release 3.0</title><pubDate>Mon, 21 Sep 2026 10:00:00 GMT</pubDate></item></channel></rss>"""
ATOM = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Blog</title>
<entry><title>Release 4.0</title><updated>2026-09-22T00:00:00Z</updated></entry></feed>"""
EVIL = """<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><rss><channel><item><title>&a;</title></item></channel></rss>"""


@pytest.mark.parametrize("body,title", [(RSS, "Release 3.0"), (ATOM, "Release 4.0")])
def test_rss_and_atom(http, body, title):
    url = "https://blog.example/feed.xml"
    http.add(url, body, content_type="application/xml")
    ev = evidence_for(claim(source_type="rss", source_url=url), frozenset({url}))
    assert title in ev.excerpt and ev.version


def test_rss_refuses_doctype(http):
    url = "https://blog.example/feed.xml"
    http.add(url, EVIL, content_type="application/xml")
    with pytest.raises(SourceError, match="DOCTYPE"):
        evidence_for(claim(source_type="rss", source_url=url), frozenset({url}))


def _bom_utf16(text: str, order: str) -> bytes:
    return (b"\xff\xfe" if order == "le" else b"\xfe\xff") + text.encode(f"utf-16-{order}")


PADDED = '<?xml version="1.0"?>' + " " * 4096 + EVIL.split("?>", 1)[1]  # DTD after 4 KB of whitespace
EVIL16 = EVIL.replace('<?xml version="1.0"?>', '<?xml version="1.0" encoding="UTF-16"?>')
RSS16 = RSS.replace('<?xml version="1.0"?>', '<?xml version="1.0" encoding="UTF-16"?>')


@pytest.mark.parametrize("body", [
    EVIL.encode("utf-8"),                     # plain UTF-8
    PADDED.encode("utf-8"),                   # the old 2048-byte search never saw this one
    _bom_utf16(EVIL16, "le"),                 # UTF-16 LE: "<!DOCTYPE" is not a byte substring
    _bom_utf16(EVIL16, "be"),                 # UTF-16 BE
    b'<?xml version="1.0"?><!DOCTYPE rss SYSTEM "https://x.invalid/a.dtd"><rss/>',  # external DTD, no internal subset
], ids=["utf8", "utf8-after-4k", "utf16le", "utf16be", "external-dtd"])
def test_rss_parser_rejects_declarations_in_any_encoding(http, body):
    url = "https://blog.example/feed.xml"
    http.add(url, body, content_type="application/xml")
    with pytest.raises(SourceError, match="DOCTYPE|ENTITY"):
        evidence_for(claim(source_type="rss", source_url=url), frozenset({url}))


@pytest.mark.parametrize("order", ["le", "be"])
def test_rss_utf16_without_declarations_still_parses(http, order):
    url = "https://blog.example/feed.xml"
    http.add(url, _bom_utf16(RSS16, order), content_type="application/xml")
    ev = evidence_for(claim(source_type="rss", source_url=url), frozenset({url}))
    assert "Release 3.0" in ev.excerpt


HTML = b"<html><head><title>T</title><script>var x='Flagship models';</script></head><body><h1>Models</h1>  <p>Flagship   models: Start with <b>GPT-9</b>.</p></body></html>"


def test_page_section_strips_tags_and_scripts(http):
    url = "https://vendor.example/models"
    http.add(url, HTML, content_type="text/html; charset=utf-8")
    ev = evidence_for(claim(source_type="page_section", source_url=url, locator="Flagship models", excerpt_chars=40), frozenset({url}))
    assert ev.version is None
    assert ev.excerpt == "Flagship models: Start with GPT-9 ."[:40]


def test_page_section_excerpt_zero_returns_match_only(http):
    url = "https://vendor.example/models"
    http.add(url, HTML, content_type="text/html")
    ev = evidence_for(claim(source_type="page_section", source_url=url, locator=r"GPT-\d+", excerpt_chars=0), frozenset({url}))
    assert ev.excerpt == "GPT-9"


def test_page_section_missing_locator_is_source_error(http):
    url = "https://vendor.example/models"
    http.add(url, HTML, content_type="text/html")
    with pytest.raises(SourceError, match="locator not found"):
        evidence_for(claim(source_type="page_section", source_url=url, locator="Nonexistent heading"), frozenset({url}))


# ---- F03: lifecycle is observed, not assumed ----

def test_github_archived_repo_is_a_lifecycle_signal(http):
    http.add("https://api.github.com/repos/o/r", json.dumps({"archived": True}))
    http.add("https://api.github.com/repos/o/r/releases/latest", json.dumps({"tag_name": "v1.2.3", "published_at": "x", "body": ""}))
    ev = evidence_for(gh(), ALLOW_GH)
    assert ev.lifecycle == ("github o/r is archived",) and "LIFECYCLE" in ev.excerpt


@pytest.mark.parametrize("body", ["This project is deprecated; use NewThing.", "v3 reaches End of Life on 2026-12-31"])
def test_github_release_notes_mentioning_deprecation_or_eol_are_signals(repo, http, body):
    http.add("https://api.github.com/repos/o/r/releases/latest", json.dumps({"tag_name": "v9", "published_at": "x", "body": body}))
    ev = evidence_for(gh(), ALLOW_GH)
    assert len(ev.lifecycle) == 1 and "v9" in ev.lifecycle[0]


def test_github_clean_release_keeps_the_old_excerpt_byte_for_byte(repo, http):
    """No signal, no change: existing snapshot hashes keep matching after the adapter upgrade."""
    http.add("https://api.github.com/repos/o/r/releases/latest", json.dumps({"tag_name": "v1", "published_at": "2026-09-01T00:00:00Z", "body": "fixes"}))
    ev = evidence_for(gh(), ALLOW_GH)
    assert ev.excerpt == "o/r latest release v1 published 2026-09-01T00:00:00Z" and ev.lifecycle == ()


def test_npm_deprecated_field_is_reported(http):
    http.add("https://registry.npmjs.org/old/latest", json.dumps({"version": "1.0.0", "description": "x",
                                                                  "deprecated": "Use @new/thing instead"}))
    ev = evidence_for(claim(source_type="npm", source_url="https://www.npmjs.com/package/old"),
                      frozenset({"https://registry.npmjs.org/old/latest"}))
    assert ev.lifecycle == ("npm deprecated: Use @new/thing instead",)


def pypi_doc(**info):
    return {"info": {"version": "2.0.0", "summary": "Example lib", "classifiers": [], **info},
            "releases": {"1.0.0": [{"upload_time": "2026-01-01T00:00:00", "yanked": True, "yanked_reason": "broken"}],
                         "1.5.0": [{"upload_time": "2026-05-01T00:00:00", "yanked": False}],
                         "2.0.0": [{"upload_time": "2026-09-20T10:00:00", "yanked": False}]}}


def test_pypi_reports_older_yanked_releases_without_flagging(http):
    http.add("https://pypi.org/pypi/example/json", json.dumps(pypi_doc()))
    ev = evidence_for(claim(), frozenset({"https://pypi.org/pypi/example/json"}))
    assert ev.lifecycle == () and ev.notes == ("pypi yanked releases: 1.0.0",)


def test_pypi_yanked_current_release_is_a_lifecycle_signal(http):
    d = pypi_doc()
    d["releases"]["2.0.0"][0].update(yanked=True, yanked_reason="security issue")
    http.add("https://pypi.org/pypi/example/json", json.dumps(d))
    ev = evidence_for(claim(), frozenset({"https://pypi.org/pypi/example/json"}))
    assert ev.lifecycle == ("pypi 2.0.0 is yanked: security issue",)


def test_pypi_inactive_classifier_and_deprecated_summary(http):
    http.add("https://pypi.org/pypi/example/json", json.dumps(pypi_doc(
        summary="DEPRECATED: use example-ng", classifiers=["Development Status :: 7 - Inactive"])))
    ev = evidence_for(claim(), frozenset({"https://pypi.org/pypi/example/json"}))
    assert len(ev.lifecycle) == 2
