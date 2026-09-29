"""`drift approve`: owner approval only from a PR merged by the owner, only for the review events it changed.
The GitHub API is mocked; git runs against a throwaway local repository."""

import datetime as dt
import json
import subprocess

import pytest

from drift import approve as AP
from drift import auto as A
from drift import registry as R
from drift import review
from tests.conftest import claim, reviewed

N = 7
URL = f"https://github.com/{R.REPOSITORY}/pull/{N}"


def git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                        "-c", "commit.gpgsign=false", *args], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def two_claims():
    return [reviewed(claim(id="L01-a", tool="A", fetched_at="2026-09-28"), when="2026-09-28", by="claude-code"),
            reviewed(claim(id="L01-b", tool="B", fetched_at="2026-09-28"), when="2026-09-28", by="claude-code")]


@pytest.fixture
def merged(tmp_path):
    """main has two reviewed claims; a PR re-records the review of L01-a; it is merged with a merge commit."""
    repo = tmp_path / "repo"
    (repo / "registry").mkdir(parents=True)
    git(repo, "init", "-q", "-b", "main")
    reg = repo / "registry" / "claims.yaml"
    claims = two_claims()
    R.save(claims, reg)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "base")
    git(repo, "checkout", "-q", "-b", "pr")
    claims[0]["fetched_at"] = "2026-09-30"
    review.record(claims[0], "supported", "claude-code", dt.date(2026, 9, 30))
    R.save(claims, reg)
    git(repo, "commit", "-q", "-am", "review L01-a")
    head = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--no-ff", "-m", "Merge PR", "pr")
    sha = git(repo, "rev-parse", "HEAD")
    pr = {"number": N, "merged": True, "merged_by": {"login": R.OWNER_LOGIN}, "merged_at": "2026-10-02T10:00:00Z",
          "merge_commit_sha": sha, "html_url": URL, "head": {"sha": head},
          "base": {"ref": "main", "repo": {"full_name": R.REPOSITORY}}}
    return {"repo": repo, "reg": reg, "pr": pr}


def run(merged, monkeypatch, pr=None, *extra):
    monkeypatch.setattr(AP, "fetch_pr", lambda n: pr or merged["pr"])
    return AP.main(["--pr", str(N), "--registry", str(merged["reg"]), "--repo-dir", str(merged["repo"]), *extra])


def test_stamps_only_the_review_event_the_pr_changed(merged, monkeypatch):
    assert run(merged, monkeypatch) == 0
    a, b = R.load(merged["reg"])
    assert (a["approved_by"], a["approved_at"], a["approval_ref"]) == (R.OWNER_LOGIN, "2026-10-02", URL)
    assert R.owner_approved(a) and R.review_state(a) == "valid" and R.publishable(a) == []
    assert not any(k in b for k in R.APPROVAL_KEYS) and not R.owner_approved(b)
    assert a["reviewed_by"] == "claude-code" and a["reviewed_at"] == "2026-09-30"  # the assessment is unchanged


@pytest.mark.parametrize("change,msg", [
    ({"merged": False}, "not merged"),
    ({"merged_by": {"login": "someone-else"}}, "not Double00kevin"),
    ({"merged_by": None}, "merged by None"),
    ({"base": {"ref": "dev", "repo": {"full_name": R.REPOSITORY}}}, "base is not main"),
    ({"base": {"ref": "main", "repo": {"full_name": "fork/other"}}}, "base is not main"),
    ({"html_url": "https://github.com/fork/other/pull/7"}, "html_url"),
    ({"number": 8}, "not 7"),
])
def test_refuses_unless_merged_by_the_owner_into_main(merged, monkeypatch, capsys, change, msg):
    before = merged["reg"].read_bytes()
    assert run(merged, monkeypatch, {**merged["pr"], **change}) == 1
    assert msg in capsys.readouterr().err and merged["reg"].read_bytes() == before


def test_refuses_a_pr_that_changed_no_review_event(merged, monkeypatch, capsys):
    repo = merged["repo"]
    (repo / "notes.txt").write_text("x", encoding="utf-8")
    git(repo, "add", "notes.txt")
    git(repo, "commit", "-q", "-m", "unrelated")
    pr = {**merged["pr"], "merge_commit_sha": git(repo, "rev-parse", "HEAD")}
    assert run(merged, monkeypatch, pr) == 1 and "nothing to approve" in capsys.readouterr().err


def test_refuses_when_the_event_changed_after_the_merge(merged, monkeypatch, capsys):
    claims = R.load(merged["reg"])
    review.record(claims[0], "partial", "claude-code", dt.date(2026, 10, 1))
    R.save(claims, merged["reg"])
    before = merged["reg"].read_bytes()
    assert run(merged, monkeypatch) == 1
    assert "changed after PR 7" in capsys.readouterr().err and merged["reg"].read_bytes() == before


def test_refuses_to_approve_twice_and_dry_run_writes_nothing(merged, monkeypatch, capsys):
    before = merged["reg"].read_bytes()
    assert run(merged, monkeypatch, None, "--dry-run") == 0 and merged["reg"].read_bytes() == before
    assert run(merged, monkeypatch) == 0
    assert run(merged, monkeypatch) == 1 and "already approved" in capsys.readouterr().err


def test_refuses_when_the_merge_commit_is_not_fetched(merged, monkeypatch, capsys):
    assert run(merged, monkeypatch, {**merged["pr"], "merge_commit_sha": "0" * 40}) == 1
    assert "git fetch" in capsys.readouterr().err


@pytest.mark.parametrize("field,value", [("approved_by", "someone-else"), ("approved_at", "2026-10-09"),
                                         ("approval_ref", f"https://github.com/{R.REPOSITORY}/pull/8"),
                                         ("reviewed_by", "claude")])
def test_editing_an_approval_voids_the_event(merged, monkeypatch, field, value):
    assert run(merged, monkeypatch) == 0
    a = R.load(merged["reg"])[0]
    a[field] = value
    assert not R.owner_approved(a) and R.review_state(a) == "void" and R.publishable(a)


def test_hand_written_approval_fields_are_rejected_unless_complete_and_the_owners():
    c = reviewed(claim(fetched_at="2026-09-28"), when="2026-09-28")
    with pytest.raises(R.RegistryError, match="incomplete owner approval"):
        R.validate([dict(c, approved_by=R.OWNER_LOGIN)])
    with pytest.raises(R.RegistryError, match="must name Double00kevin"):
        R.validate([dict(c, approved_by="mallory", approved_at="2026-10-01", approval_ref=URL)])
    with pytest.raises(R.RegistryError, match="before the review"):
        R.validate([dict(c, approved_by=R.OWNER_LOGIN, approved_at="2026-09-01", approval_ref=URL)])


def test_approval_does_not_void_an_automated_re_check_made_before_it(merged, monkeypatch):
    claims = R.load(merged["reg"])
    a = claims[0]
    A.apply(a, [{"id": a["id"], "receipt": 0, "reasons": [], "old_hash": a["snapshot_hash"],
                 "new_hash": a["snapshot_hash"], "new_excerpt": a["snapshot"]}], "unchanged", dt.date(2026, 10, 3))
    R.save(claims, merged["reg"])
    assert run(merged, monkeypatch) == 0
    a = R.load(merged["reg"])[0]
    assert R.auto_state(a) == "valid" and R.owner_approved(a) and R.publishable(a) == []


def test_owner_is_one_config_value_not_an_argument():
    import inspect
    assert R.OWNER_LOGIN == "Double00kevin"
    assert "--owner" not in inspect.getsource(AP.main)


def test_fetch_pr_uses_the_token_without_printing_it(monkeypatch, capsys):
    seen = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            return json.dumps({"number": N}).encode()

    def fake(req, timeout):
        seen.update(url=req.full_url, auth=req.get_header("Authorization"), timeout=timeout)
        return Resp()

    fake_token = "x" * 8 + "-fake-" + "y" * 8  # built at runtime; not a real credential
    monkeypatch.setenv("GITHUB_TOKEN", fake_token)
    monkeypatch.setattr(AP.urllib.request, "urlopen", fake)
    assert AP.fetch_pr(N) == {"number": N}
    assert seen["url"] == f"https://api.github.com/repos/{R.REPOSITORY}/pulls/{N}" and seen["timeout"] == AP.TIMEOUT_S
    assert seen["auth"] == f"Bearer {fake_token}" and fake_token not in capsys.readouterr().out


def test_token_is_never_forwarded_on_a_redirect(monkeypatch):
    """urllib copies ordinary headers onto a redirected request; the token must be an unredirected header."""
    captured = {}

    def fake(req, timeout):
        captured["req"] = req
        raise OSError("stop")

    monkeypatch.setenv("GITHUB_TOKEN", "t" * 12)
    monkeypatch.setattr(AP.urllib.request, "urlopen", fake)
    with pytest.raises(AP.ApprovalError):
        AP.fetch_pr(N)
    req = captured["req"]
    assert "Authorization" not in req.headers and req.unredirected_hdrs.get("Authorization") == "Bearer " + "t" * 12


def test_a_non_object_api_response_is_refused(monkeypatch):
    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n):
            return b"[1, 2]"

    monkeypatch.setattr(AP.urllib.request, "urlopen", lambda req, timeout: Resp())
    with pytest.raises(AP.ApprovalError, match="not a pull request object"):
        AP.fetch_pr(N)
