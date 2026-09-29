"""Failure-path regressions from the follow-up audit. No network or real remote publication."""
import datetime as dt
import json
import subprocess

import pytest

from drift import auto as A, check as C, mapgen as M, registry as R, snapshot as S
from drift.sources import Evidence
from render import render_map as RM
from tests.conftest import claim, reviewed
from tests.test_auto import TODAY, finding, write_report, world  # noqa: F401 (fixture)
from tests.test_map import _published, mini_claims


@pytest.mark.parametrize("previous_auto", [False, True])
def test_snapshot_cannot_restart_a_broken_review_chain(monkeypatch, previous_auto):
    c = reviewed(claim(source_type="page_section", locator="Service", snapshot="Service is offered.",
                       snapshot_hash=R.excerpt_sha256("Service is offered.")),
                 when=(TODAY - dt.timedelta(days=10)).isoformat())
    if previous_auto:
        A.apply(c, [finding(c)], "unchanged", TODAY - dt.timedelta(days=1))
    ev = Evidence(None, "Service has permanently shut down.")
    monkeypatch.setattr(S, "evidence_for", lambda *a: ev)
    R.set_receipt(c, 0, S.snapshot_one(c, frozenset(), TODAY.isoformat()))
    assert R.review_state(c) == "void"
    findings = [C.finding_dict(C.compare(c, ev, TODAY))]
    assert not A.decide(c, findings, TODAY)[0]
    with pytest.raises(R.RegistryError, match="review chain"):
        A.apply(c, findings, "unchanged", TODAY)
    assert R.publishable(c)


@pytest.mark.parametrize("field,value", [("source_type", "npm"), ("locator", "different"),
                                         ("excerpt_chars", 1), ("redirect_to", "https://example.invalid/new")])
@pytest.mark.parametrize("additional", [False, True])
def test_review_binds_source_extraction_configuration(field, value, additional):
    c = reviewed(claim())
    if additional:
        c['sources'] = [R.receipts(c)[0]]
        reviewed(c)
        c['sources'][0][field] = value
    else:
        c[field] = value
    assert R.review_state(c) == "void"
    assert R.claim_hash(c) != c['review_claim_hash']


def test_changed_excerpt_is_not_trusted_just_because_report_reasons_are_empty():
    c = reviewed(claim(source_type="page_section", locator="x"))
    f = finding(c, new="Changed meaning", reasons=[])
    assert not A.decide(c, [f], TODAY)[0]


@pytest.mark.parametrize("missing", ["new_excerpt", "new_hash"])
def test_unchanged_receipts_require_complete_fresh_evidence(missing):
    c = reviewed(claim())
    f = finding(c)
    f.pop(missing)
    assert not A.decide(c, [f], TODAY)[0]


def test_failed_render_is_an_error_leaves_no_version_and_can_retry(world, monkeypatch):
    rep = write_report(world['tmp'], world['reg'], [finding(c) for c in world['claims']])
    argv = ['--report', str(rep), '--registry', str(world['reg']), '--maps-dir', str(world['maps']),
            '--reports-dir', str(world['tmp'] / 'reports')]
    before = world['reg'].read_bytes()
    versions = M.existing_versions(world['maps'])
    monkeypatch.setattr(A, 'needs_version', lambda *a: (True, 'test renewal due'))
    with monkeypatch.context() as fail:
        fail.setattr(A.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess([], 1, '', 'renderer failed'))
        assert A.main(argv) == A.EXIT_ERROR
    assert world['reg'].read_bytes() == before
    assert M.existing_versions(world['maps']) == versions
    assert not list(world['maps'].glob('.publish-*'))
    assert A.main(argv) == A.EXIT_OK
    newest = M.latest_map(world['maps'])
    assert newest.parent.name == f'v{TODAY:%Y.%m.%d}'
    assert not M.verify_image(newest.parent, json.loads(newest.read_text(encoding='utf-8')))


def test_document_promotion_failure_restores_registry_docs_and_version(world, monkeypatch):
    root = world['tmp']
    monkeypatch.setattr(M, 'MAPS_DIR', world['maps'])
    monkeypatch.setattr(M, 'README', root / 'README.md')
    monkeypatch.setattr(M, 'MAP_MD', root / 'MAP.md')
    monkeypatch.setattr(R, 'ROOT', root)
    for p, content in [(M.README, M.README_BEGIN + '\n' + M.README_END), (M.MAP_MD, 'original map'),
                       (root / 'CHANGELOG.md', '# Changelog\n\n## old\n')]:
        p.write_text(content, encoding='utf-8')
    before = {p: p.read_bytes() for p in [world['reg'], M.README, M.MAP_MD, root / 'CHANGELOG.md']}
    versions = M.existing_versions(world['maps'])
    def render(argv, **kw):
        RM.main([argv[2], '--historical'])
        return subprocess.CompletedProcess(argv, 0, '', '')
    monkeypatch.setattr(A.subprocess, 'run', render)
    real_replace = A.os.replace
    def fail_readme(source, target):
        if target == M.README:
            raise OSError('simulated document promotion failure')
        return real_replace(source, target)
    monkeypatch.setattr(A.os, 'replace', fail_readme)
    with pytest.raises(OSError, match='promotion failure'):
        A.build_version(world['claims'], f'v{TODAY:%Y.%m.%d}', TODAY, 'renewal',
                        {'renewed': 69, 'needs_owner': 0}, world['maps'], world['reg'])
    assert all(p.read_bytes() == content for p, content in before.items())
    assert M.existing_versions(world['maps']) == versions


@pytest.mark.parametrize('field,value', [('expires', '2099-12-31'), ('oldest_check', '2099-12-01'),
                                      ('oldest_review', '2020-01-01'), ('trust_window_days', 999)])
def test_verifier_rejects_dates_even_when_documents_match(tmp_path, monkeypatch, field, value):
    reg, maps, readme, md = _published(tmp_path, monkeypatch, mini_claims())
    path = M.latest_map(maps)
    m = json.loads(path.read_text(encoding='utf-8'))
    m[field] = value
    path.write_text(M.map_json_text(m), encoding='utf-8')
    readme.write_text(M.render_readme_block(m), encoding='utf-8')
    md.write_text(M.render_map_markdown(m), encoding='utf-8')
    assert not M.verify(maps, reg, readme, md, render=False)[0]
    assert not M.check_expiry(path, dt.date(2026, 9, 28))[0]


@pytest.mark.parametrize('damage', ['invalid', 'wrong_pixels', 'wrong_size'])
def test_verifier_checks_committed_pixels_not_only_the_sidecar(tmp_path, monkeypatch, damage):
    from PIL import Image
    reg, maps, readme, md = _published(tmp_path, monkeypatch, mini_claims())
    path = M.latest_map(maps)
    RM.main([str(path), '--historical'])
    assert M.verify(maps, reg, readme, md)[0]
    png = path.with_name('map.png')
    if damage == 'invalid':
        png.write_bytes(b'not a PNG')
    elif damage == 'wrong_size':
        Image.new('RGB', (1, 1)).save(png)
    else:
        with Image.open(png) as im:
            im.putpixel((100, 100), (255, 0, 0))
            im.save(png)
    ok, errors = M.verify(maps, reg, readme, md)
    assert not ok and any('map.png' in e for e in errors)
