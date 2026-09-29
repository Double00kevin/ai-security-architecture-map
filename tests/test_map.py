"""map.json is generated from the registry, names match exactly, and an expired map fails the check."""

import datetime as dt
import json

import pytest

from drift import mapgen as M
from drift import registry as R
from tests.conftest import claim, reviewed

CTL = [{"layer": i, "name": f"Layer {i}", "control": f"Control {i}"} for i in range(1, 13)]


def mini_claims(reviewed_on="2026-09-27"):
    out = []
    for layer, n in enumerate(R.LAYER_COUNTS, start=1):
        for k in range(n):
            c = claim(id=f"L{layer:02d}-t{k}", layer=layer, layer_name=f"Layer {layer}", tool=f"Tool {layer}.{k}",
                      last_version="1.0", fetched_at="2026-09-27")
            out.append(reviewed(c, when=reviewed_on) if reviewed_on else c)
    return out


def build_cli(tmp_path, claims, version, today="2026-09-28", maps=None):
    import yaml
    reg = tmp_path / "claims.yaml"
    reg.write_text(yaml.safe_dump({"claims": claims}, sort_keys=False), encoding="utf-8")  # unvalidated on purpose
    ctl = tmp_path / "controls.yaml"
    ctl.write_text(yaml.safe_dump({"controls": CTL}), encoding="utf-8")
    return M.main(["build", "--version", version, "--registry", str(reg), "--controls", str(ctl),
                   "--maps-dir", str(maps or tmp_path / "maps"), "--today", today])


def test_build_map_has_every_tool_once_spelled_exactly():
    claims = mini_claims()
    m = M.build_map(claims, CTL, "v2026.09.27")
    M.validate_map(m, claims)
    assert m["counts"]["tools"] == 69 and m["counts"]["per_layer"] == R.LAYER_COUNTS
    assert m["date"] == "2026-09-27" and m["expires"] == "2026-10-27" and m["oldest_review"] == "2026-09-27"
    assert m["layers"][6]["control"] == "Control 7"
    names = [t["name"] for layer in m["layers"] for t in layer["tools"]]
    assert names == [c["tool"] for c in claims]  # registry order is display order


def test_validate_rejects_misspelled_or_missing_tool():
    claims = mini_claims()
    m = M.build_map(claims, CTL, "v2026.09.27")
    m["layers"][0]["tools"][0]["name"] = "Tool 1.0 "  # trailing space is a spelling difference
    with pytest.raises(M.MapError, match="mismatch"):
        M.validate_map(m, claims)


def test_layer_name_mismatch_is_an_error():
    claims = mini_claims()
    claims[0]["layer_name"] = "Something Else"
    with pytest.raises(M.MapError, match="layer 1"):
        M.build_map(claims, CTL, "v2026.09.27")


def test_bad_version_string():
    with pytest.raises(M.MapError):
        M.version_date("2026-09-27")


def test_expired_map_fails_check(tmp_path):
    m = M.build_map(mini_claims(), CTL, "v2026.09.27")
    M.write_map(m, tmp_path)
    ok, msg = M.check_expiry(M.latest_map(tmp_path), dt.date(2026, 10, 27))
    assert ok and "0 day(s) left" in msg
    ok, msg = M.check_expiry(M.latest_map(tmp_path), dt.date(2026, 10, 28))
    assert not ok and "EXPIRED 1 day" in msg
    assert M.main(["check", "--maps-dir", str(tmp_path), "--today", "2026-10-28"]) == 1
    assert M.main(["check", "--maps-dir", str(tmp_path), "--today", "2026-10-01"]) == 0


def test_latest_map_picks_newest_version_and_missing_fails(tmp_path):
    assert M.main(["check", "--maps-dir", str(tmp_path), "--today", "2026-10-01"]) == 1  # nothing built yet
    for v in ("v2026.09.27", "v2026.10.04", "v2026.08.01"):
        M.write_map(M.build_map(mini_claims(), CTL, v), tmp_path)
    assert M.latest_map(tmp_path).parent.name == "v2026.10.04"


def test_real_registry_builds_a_valid_map():
    claims = R.load()
    m = M.build_map(claims, M.load_controls(), "v2026.09.28")
    M.validate_map(m, claims)
    assert json.dumps(m)  # serialisable
    assert m["layers"][1]["tools"][1]["name"] == "Prisma AIRS (Portkey)"


def test_candidates_are_not_rendered():
    claims = mini_claims() + [claim(id="L01-cand", layer=1, layer_name="Layer 1", tool="Candidate", on_map=False)]
    m = M.build_map(claims, CTL, "v2026.09.27", governance=[{"name": "NIST AI RMF", "source_url": "https://www.nist.gov/itl/ai-risk-management-framework"}])
    M.validate_map(m, claims)
    assert "Candidate" not in [t["name"] for t in m["layers"][0]["tools"]]
    assert m["counts"]["tools"] == 69 and m["governance"][0]["name"] == "NIST AI RMF"


def test_write_map_refuses_to_overwrite_a_published_version(tmp_path):
    M.write_map(M.build_map(mini_claims(), CTL, "v2026.09.27"), tmp_path)
    with pytest.raises(M.MapError, match="already exists"):
        M.write_map(M.build_map(mini_claims(), CTL, "v2026.09.27"), tmp_path)


def test_same_day_reissue_sorts_after_base_version(tmp_path):
    for v in ("v2026.09.27", "v2026.09.27.1"):
        M.write_map(M.build_map(mini_claims(), CTL, v), tmp_path)
    assert M.latest_map(tmp_path).parent.name == "v2026.09.27.1"
    assert M.version_date("v2026.09.27.1") == dt.date(2026, 9, 27)


def test_readme_block_and_map_md_match_latest_map():
    """README's generated table and MAP.md list exactly the tools of the newest map.json."""
    p = M.latest_map()
    if p is None:
        pytest.skip("no map built")
    m = json.loads(p.read_text(encoding="utf-8"))
    names = [t["name"] for layer in m["layers"] for t in layer["tools"]]
    readme = M.README.read_text(encoding="utf-8")
    block = readme[readme.index(M.README_BEGIN): readme.index(M.README_END)]
    assert block.strip() == M.render_readme_block(m).replace(M.README_END, "").strip()
    assert all(n in block for n in names) and m["version"] in block
    map_md = M.MAP_MD.read_text(encoding="utf-8")
    assert all(f"| {n} |" in map_md for n in names) and m["expires"] in map_md


# ---- F01 / F05 / F24: validity is bound to reviewed evidence, not to the version string ----

def test_build_refuses_claims_last_seen_in_2020_without_review(tmp_path, capsys):
    """The audit's repro: evidence from 2020 and no review. Before: built fine. Now: refused."""
    claims = mini_claims(reviewed_on=None)
    for c in claims:
        c["fetched_at"] = "2020-01-01"
    assert build_cli(tmp_path, claims, "v2026.09.28") == 1
    assert "review missing" in capsys.readouterr().err
    assert not (tmp_path / "maps").exists()


def test_old_review_expires_the_map_even_with_a_fresh_version(tmp_path):
    claims = mini_claims(reviewed_on="2026-09-27")
    reviewed(claims[5], when="2026-09-01")  # one old review drags expiry forward
    m = M.build_map(claims, CTL, "v2026.09.28")
    assert m["expires"] == "2026-10-01" and m["oldest_review"] == "2026-09-01"
    assert build_cli(tmp_path, claims, "v2026.09.28") == 0
    ok, msg = M.check_expiry(M.latest_map(tmp_path / "maps"), dt.date(2026, 10, 2))
    assert not ok and "EXPIRED" in msg


def test_build_refuses_future_version(tmp_path, capsys):
    assert build_cli(tmp_path, mini_claims(), "v2099.01.01") == 1
    assert "in the future" in capsys.readouterr().err


def test_build_refuses_version_earlier_than_newest(tmp_path, capsys):
    maps = tmp_path / "maps"
    assert build_cli(tmp_path, mini_claims(), "v2026.09.28", maps=maps) == 0
    assert build_cli(tmp_path, mini_claims(), "v2026.09.27", maps=maps) == 1
    assert "earlier than the newest" in capsys.readouterr().err
    assert build_cli(tmp_path, mini_claims(), "v2026.09.28", maps=maps) == 1  # same version: never rewritten
    assert build_cli(tmp_path, mini_claims(), "v2026.09.28.1", maps=maps) == 0  # same-day re-issue


def test_build_refuses_claim_without_snapshot(tmp_path, capsys):
    claims = mini_claims()
    claims[0].update(snapshot=None, snapshot_hash=None)
    assert build_cli(tmp_path, claims, "v2026.09.28") == 1
    err = capsys.readouterr().err
    assert "L01-t0" in err and "no snapshot/hash" in err


def test_build_refuses_layer_99(tmp_path, capsys):
    claims = mini_claims()
    claims[0].update(layer=99, id="L99-t0")
    assert build_cli(tmp_path, claims, "v2026.09.28") == 1
    assert "1..12" in capsys.readouterr().err


def test_build_refuses_duplicate_layer_tool(tmp_path, capsys):
    claims = mini_claims()
    claims[1]["tool"] = claims[0]["tool"]
    assert build_cli(tmp_path, claims, "v2026.09.28") == 1
    assert "duplicate on-map tool" in capsys.readouterr().err


def test_validate_map_catches_duplicates_that_a_set_compare_misses():
    claims = mini_claims()
    m = M.build_map(claims, CTL, "v2026.09.27")
    m["layers"][0]["tools"].append(dict(m["layers"][0]["tools"][0]))  # same tool twice
    with pytest.raises(M.MapError):
        M.validate_map(m, claims)


def test_build_refuses_void_review(tmp_path, capsys):
    claims = mini_claims()
    claims[3]["claim"] = "Tool 1.3 is active and now also does X"  # edited after review
    assert build_cli(tmp_path, claims, "v2026.09.28") == 1
    assert "review void" in capsys.readouterr().err


@pytest.mark.parametrize("outcome", ["partial", "unsupported"])
def test_build_refuses_non_supported_review(tmp_path, capsys, outcome):
    claims = mini_claims()
    reviewed(claims[2], outcome=outcome)
    assert build_cli(tmp_path, claims, "v2026.09.28") == 1
    assert f"'{outcome}'" in capsys.readouterr().err


def test_candidates_need_no_review(tmp_path):
    claims = mini_claims() + [claim(id="L01-cand", layer=1, layer_name="Layer 1", tool="Candidate", on_map=False)]
    assert build_cli(tmp_path, claims, "v2026.09.28") == 0


def test_governance_past_review_is_warned(tmp_path, capsys):
    import yaml
    gov = tmp_path / "gov.yaml"
    gov.write_text(yaml.safe_dump({"governance": [
        {"name": "A", "source_url": "https://a.invalid/", "reviewed_at": "2026-08-01", "review_due": "2026-08-31"},
        {"name": "B", "source_url": "https://b.invalid/", "reviewed_at": "2026-09-27", "review_due": "2026-10-27"}]}),
        encoding="utf-8")
    reg = tmp_path / "claims.yaml"
    R.save(mini_claims(), reg)
    ctl = tmp_path / "controls.yaml"
    ctl.write_text(yaml.safe_dump({"controls": CTL}), encoding="utf-8")
    assert M.main(["build", "--version", "v2026.09.28", "--registry", str(reg), "--controls", str(ctl),
                   "--governance", str(gov), "--maps-dir", str(tmp_path / "maps"), "--today", "2026-09-28"]) == 0
    err = capsys.readouterr().err
    assert "WARNING: governance A: review was due 2026-08-31" in err and "governance B" not in err


def test_real_governance_entries_carry_review_fields():
    for g in M.load_governance():
        assert g["reviewed_at"] and g["review_due"], g["name"]
        assert "last_checked" not in g


def test_verify_detects_a_hand_edit(tmp_path, monkeypatch):
    """F12: rebuild from inputs and diff; a hand edit to a generated file fails."""
    import yaml
    claims = mini_claims()
    reg = tmp_path / "claims.yaml"
    R.save(claims, reg)
    ctl = tmp_path / "controls.yaml"
    ctl.write_text(yaml.safe_dump({"controls": CTL}), encoding="utf-8")
    monkeypatch.setattr(M, "load_controls", lambda *a, **k: CTL)
    maps = tmp_path / "maps"
    m = M.build_map(claims, CTL, "v2026.09.28", M.load_governance(), M.load_copy())
    M.write_map(m, maps)
    readme, map_md = tmp_path / "README.md", tmp_path / "MAP.md"
    readme.write_text("x\n" + M.render_readme_block(m) + "\ny\n", encoding="utf-8")
    map_md.write_text(M.render_map_markdown(m), encoding="utf-8")
    ok, msgs = M.verify(maps, reg, readme, map_md, render=False)
    assert ok, msgs
    map_md.write_text(M.render_map_markdown(m).replace("Tool 1.0", "Tool 1.0 (edited)"), encoding="utf-8")
    ok, msgs = M.verify(maps, reg, readme, map_md, render=False)
    assert not ok and "MAP.md differs" in msgs[0]


def test_committed_newest_map_verifies_against_the_registry():
    """The newest committed map must still be backed by publishable claims and match the registry's content."""
    p = M.latest_map()
    assert json.loads(p.read_text(encoding="utf-8"))["schema_version"] >= 2
    ok, msgs = M.verify(render=False)
    assert ok, msgs


def test_unpinned_legacy_schema_map_fails_verification(tmp_path):
    """A02: a schema-1 map.json under a historical version id is not a pass just because it says 'legacy'."""
    legacy = tmp_path / "v2026.09.27.1"
    legacy.mkdir()
    (legacy / "map.json").write_text(json.dumps({"schema_version": 1, "version": "v2026.09.27.1"}), encoding="utf-8")
    ok, msgs = M.verify(tmp_path)
    assert not ok and "schema" in msgs[0]
    assert M.verify_publication(tmp_path)[0] == "failed"


# ---- PR #5 review: R3 (verify enforces reviews), R7 (no already-expired build), R8 (counts) ----

def _published(tmp_path, monkeypatch, claims, version="v2026.09.28"):
    reg = tmp_path / "claims.yaml"
    R.save(claims, reg)
    monkeypatch.setattr(M, "load_controls", lambda *a, **k: CTL)
    maps = tmp_path / "maps"
    m = M.build_map(claims, CTL, version, M.load_governance(), M.load_copy())
    M.write_map(m, maps)
    readme, map_md = tmp_path / "README.md", tmp_path / "MAP.md"
    readme.write_text("x\n" + M.render_readme_block(m) + "\ny\n", encoding="utf-8")
    map_md.write_text(M.render_map_markdown(m), encoding="utf-8")
    return reg, maps, readme, map_md


def test_verify_fails_when_a_published_claim_loses_its_review(tmp_path, monkeypatch):
    """R3: a material claim edit voids its review; the rendered map is unchanged, verify must still fail."""
    claims = mini_claims(reviewed_on="2026-09-28")
    reg, maps, readme, map_md = _published(tmp_path, monkeypatch, claims)
    assert M.verify(maps, reg, readme, map_md, render=False)[0]
    claims[0]["claim"] = "Tool 1.0 is the best model ever made"  # not re-reviewed
    R.save(claims, reg)
    ok, msgs = M.verify(maps, reg, readme, map_md, render=False)
    assert not ok and "no longer publishable" in msgs[0] and "L01-t0" in msgs[0] and "review void" in msgs[0]


def test_verify_fails_when_reviewed_content_changed_but_no_new_version_ships(tmp_path, monkeypatch):
    """A reviewed change a reader would see (here: an owner) needs a new version before verify passes."""
    from drift import review
    claims = mini_claims(reviewed_on="2026-09-28")
    reg, maps, readme, map_md = _published(tmp_path, monkeypatch, claims)
    claims[0].update(owner="BigCo", assertions=["availability", "ownership"], supports=["availability", "ownership"])
    review.record(claims[0], "supported", "tester", dt.date(2026, 9, 28))
    R.save(claims, reg)
    ok, msgs = M.verify(maps, reg, readme, map_md, render=False)
    assert not ok and any("map content no longer matches the registry" in x and "BigCo" in x for x in msgs)


def test_verify_passes_after_a_re_check_that_changes_no_content(tmp_path, monkeypatch):
    """Weekly re-checks renew evidence and dates; the published version stays valid until content changes."""
    from drift import review
    claims = mini_claims(reviewed_on="2026-09-28")
    reg, maps, readme, map_md = _published(tmp_path, monkeypatch, claims)
    claims[0]["claim"] = "Tool 1.0 is an actively offered model family"  # claim text is not map content
    review.record(claims[0], "supported", "tester", dt.date(2026, 9, 30))
    R.save(claims, reg)
    ok, msgs = M.verify(maps, reg, readme, map_md, render=False)
    assert ok, msgs


def test_verify_fails_when_an_excerpt_no_longer_matches_its_digest(tmp_path, monkeypatch):
    claims = mini_claims(reviewed_on="2026-09-28")
    reg, maps, readme, map_md = _published(tmp_path, monkeypatch, claims)
    claims[3]["snapshot"] += " (edited)"
    R.save(claims, reg)
    ok, msgs = M.verify(maps, reg, readme, map_md, render=False)
    assert not ok and "does not match its excerpt" in msgs[0]


def test_build_refuses_a_map_that_is_already_expired(tmp_path):
    """R7: supported, hash-valid reviews from 2020 give an honest 2020 expiry; build must refuse, not write it."""
    rc = build_cli(tmp_path, mini_claims(reviewed_on="2020-01-01"), "v2026.09.28", today="2026-09-28")
    assert rc == 1
    assert not (tmp_path / "maps" / "v2026.09.28").exists()


def test_build_accepts_a_review_30_days_old_and_refuses_31(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    assert build_cli(tmp_path / "a", mini_claims(reviewed_on="2026-08-29"), "v2026.09.28", today="2026-09-28") == 0
    assert build_cli(tmp_path / "b", mini_claims(reviewed_on="2026-08-28"), "v2026.09.28", today="2026-09-28") == 1


@pytest.mark.parametrize("field,value", [("tools", 999), ("layers", 999), ("controls", 11),
                                         ("per_layer", [99] + R.LAYER_COUNTS[1:])])
def test_validate_map_recomputes_serialized_counts(field, value):
    """R8: a map whose counts were edited must not validate."""
    claims = mini_claims()
    m = M.build_map(claims, CTL, "v2026.09.27")
    M.validate_map(m, claims)
    m["counts"][field] = value
    with pytest.raises(M.MapError, match="serialized counts"):
        M.validate_map(m, claims)


def test_validate_map_recomputes_expiry():
    claims = mini_claims()
    m = M.build_map(claims, CTL, "v2026.09.27")
    m["expires"] = "2099-01-01"
    with pytest.raises(M.MapError, match="expires/oldest_check"):
        M.validate_map(m, claims)
    with pytest.raises(M.MapError, match="publication expires"):
        M.validate_map(m, claims, dates=False)  # historical dates still have to obey the publication policy


@pytest.mark.parametrize("missing", ["map.txt", "map.png"])
def test_verify_fails_when_the_rendered_png_or_its_sidecar_is_missing(tmp_path, monkeypatch, missing):
    """A schema-2 map committed before rendering must not verify: the README points at map.png."""
    import yaml
    claims = mini_claims()
    reg = tmp_path / "claims.yaml"
    R.save(claims, reg)
    monkeypatch.setattr(M, "load_controls", lambda *a, **k: CTL)
    maps = tmp_path / "maps"
    m = M.build_map(claims, CTL, "v2026.09.28", M.load_governance(), M.load_copy())
    out = M.write_map(m, maps)
    other = {"map.txt": "map.png", "map.png": "map.txt"}[missing]
    (out.parent / other).write_text("present\n", encoding="utf-8")
    readme, map_md = tmp_path / "README.md", tmp_path / "MAP.md"
    readme.write_text("x\n" + M.render_readme_block(m) + "\ny\n", encoding="utf-8")
    map_md.write_text(M.render_map_markdown(m), encoding="utf-8")
    ok, msgs = M.verify(maps, reg, readme, map_md, render=True)
    assert not ok and any(missing in s and "missing" in s for s in msgs), msgs


# ---- A02 (2026-09-29 audit): the current publication must be the current schema ----

def _rewrite(path, m, readme, md):
    path.write_text(M.map_json_text(m), encoding="utf-8")
    if m.get("layers") is not None and m.get("version"):
        readme.write_text("x\n" + M.render_readme_block(m) + "\ny\n", encoding="utf-8")
        md.write_text(M.render_map_markdown(m), encoding="utf-8")


def _cli(maps, reg, readme, md, *cmd):
    return M.main([*cmd, "--maps-dir", str(maps)] + (["--registry", str(reg), "--readme", str(readme),
                                                     "--map-md", str(md), "--no-render"] if cmd[0] == "verify" else
                                                    ["--today", "2026-09-28"]))


@pytest.mark.parametrize("probe", ["downgrade", "missing", "unknown", "string", "empty_layers"])
def test_schema_probes_fail_map_check_and_map_verify(tmp_path, monkeypatch, probe):
    reg, maps, readme, md = _published(tmp_path, monkeypatch, mini_claims(reviewed_on="2026-09-28"))
    assert _cli(maps, reg, readme, md, "check") == 0 and _cli(maps, reg, readme, md, "verify") == 0
    path = M.latest_map(maps)
    m = json.loads(path.read_text(encoding="utf-8"))
    if probe == "downgrade":
        m["schema_version"] = 1
    elif probe == "missing":
        del m["schema_version"]
    elif probe == "unknown":
        m["schema_version"] = 99
    elif probe == "string":
        m["schema_version"] = str(M.SCHEMA_VERSION)
    else:
        m["layers"] = []
    _rewrite(path, m, readme, md)
    assert _cli(maps, reg, readme, md, "check") == 1
    assert _cli(maps, reg, readme, md, "verify") == 1
    assert not M.check_expiry(path, dt.date(2026, 9, 28))[0]
    assert M.verify_publication(maps, reg, readme, md, render=False)[0] == "failed"


def _copy_version(src_version, dest, name=None):
    import shutil
    target = dest / (name or src_version)
    shutil.copytree(M.MAPS_DIR / src_version, target)
    return target / "map.json"


@pytest.mark.parametrize("version", sorted(M.LEGACY_MAPS))
def test_pinned_legacy_map_as_newest_is_a_distinct_non_success(tmp_path, version):
    maps = tmp_path / "maps"
    _copy_version(version, maps)
    state, msgs = M.verify_publication(maps, render=False)
    assert state == "skipped" and "legacy" in msgs[0]
    assert M.main(["verify", "--maps-dir", str(maps), "--no-render"]) == M.EXIT_LEGACY
    assert M.main(["check", "--maps-dir", str(maps), "--today", "2026-09-29"]) == M.EXIT_LEGACY
    assert M.EXIT_LEGACY not in (0, 1)


def test_legacy_pin_is_exact_version_and_digest(tmp_path):
    maps = tmp_path / "a"
    p = _copy_version("v2026.09.28", maps)
    p.write_bytes(p.read_bytes().replace(b"LiteLLM", b"LiteLLM2"))  # one edited byte range: not the pinned file
    assert M.verify_publication(maps, render=False)[0] == "failed"
    assert M.main(["check", "--maps-dir", str(maps), "--today", "2026-09-29"]) == 1
    maps = tmp_path / "b"
    _copy_version("v2026.09.28", maps, name="v2026.09.30")  # pinned bytes under another version id
    assert M.verify_publication(maps, render=False)[0] == "failed"


def test_pinned_digest_ignores_crlf_checkouts(tmp_path):
    maps = tmp_path / "maps"
    p = _copy_version("v2026.09.28", maps)
    p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
    assert M.publication_state(p)[0] == "legacy"


def test_archived_legacy_versions_stay_readable():
    for version, digest in M.LEGACY_MAPS.items():
        p = M.MAPS_DIR / version / "map.json"
        assert M.map_file_sha256(p) == digest, version
        state, m, _ = M.publication_state(p)
        assert state == "legacy" and m["version"] == version
        assert m["layers"] and M.render_map_markdown(m)
        if m["schema_version"] >= 2:
            M.validate_publication_dates(m)


def test_committed_newest_map_is_the_current_schema():
    state, m, msg = M.publication_state(M.latest_map())
    assert state == "current" and m["schema_version"] == M.SCHEMA_VERSION, msg
