import pytest

from claude_platform import vcs


# --- ensure_git: real git in a tmp dir (local only, no network) ---
def test_ensure_git_inits_commits_and_writes_gitignore(tmp_path):
    (tmp_path / "a.json").write_text("{}\n")
    made = vcs.ensure_git(tmp_path, "snap")
    assert made is True
    assert (tmp_path / ".git").is_dir()
    assert (tmp_path / ".gitignore").exists()


def test_ensure_git_second_run_no_changes_returns_false(tmp_path):
    (tmp_path / "a.json").write_text("{}\n")
    assert vcs.ensure_git(tmp_path, "snap") is True
    assert vcs.ensure_git(tmp_path, "snap2") is False     # nothing new to commit


def test_ensure_git_scopes_add_to_given_paths(tmp_path):
    import subprocess
    (tmp_path / "keep.json").write_text("{}\n")
    (tmp_path / "secret.env").write_text("x\n")
    assert vcs.ensure_git(tmp_path, "snap", paths=["keep.json"]) is True
    tracked = subprocess.run(["git", "-C", str(tmp_path), "ls-files"],
                             capture_output=True, text=True).stdout
    assert "keep.json" in tracked and "secret.env" not in tracked


def test_ensure_git_missing_git_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(vcs.shutil, "which", lambda b: None)
    with pytest.raises(vcs.VcsError, match="git"):
        vcs.ensure_git(tmp_path, "m")


# --- push_github: mock the subprocess runner (no real gh / no network) ---
def _record(monkeypatch, *, origin="", url="https://github.com/o/r.git"):
    calls = []

    def fake_run(args, cwd):
        calls.append(args)
        if args == ["git", "remote"]:
            return origin
        if args[:3] == ["git", "remote", "get-url"]:
            return url
        return ""

    monkeypatch.setattr(vcs, "_run", fake_run)
    return calls


def test_push_creates_private_repo_by_default(tmp_path, monkeypatch):
    calls = _record(monkeypatch)
    monkeypatch.setattr(vcs.shutil, "which", lambda b: f"/usr/bin/{b}")
    url = vcs.push_github(tmp_path, "o/r")
    assert url == "https://github.com/o/r.git"
    gh = next(c for c in calls if c[:1] == ["gh"])
    assert "o/r" in gh and "--private" in gh and "--public" not in gh


def test_push_public_flag(tmp_path, monkeypatch):
    calls = _record(monkeypatch)
    monkeypatch.setattr(vcs.shutil, "which", lambda b: f"/usr/bin/{b}")
    vcs.push_github(tmp_path, "o/r", private=False)
    gh = next(c for c in calls if c[:1] == ["gh"])
    assert "--public" in gh and "--private" not in gh


def test_push_existing_origin_does_not_create_repo(tmp_path, monkeypatch):
    calls = _record(monkeypatch, origin="origin")
    # gh must not even be consulted when origin already exists
    monkeypatch.setattr(vcs.shutil, "which",
                        lambda b: (_ for _ in ()).throw(AssertionError("gh should not be checked")))
    vcs.push_github(tmp_path, "o/r")
    assert not any(c[:1] == ["gh"] for c in calls)
    assert any(c[:3] == ["git", "push", "-u"] for c in calls)


def test_push_missing_gh_raises(tmp_path, monkeypatch):
    _record(monkeypatch)                       # no origin -> reaches the gh check
    monkeypatch.setattr(vcs.shutil, "which", lambda b: None)
    with pytest.raises(vcs.VcsError, match="gh"):
        vcs.push_github(tmp_path, "o/r")


def test_run_raises_on_nonzero(tmp_path):
    with pytest.raises(vcs.VcsError):
        vcs._run(["git", "rev-parse", "--verify", "definitely-not-a-ref"], tmp_path)


def test_run_missing_binary_raises_vcserror(tmp_path):
    with pytest.raises(vcs.VcsError, match="not found on PATH"):
        vcs._run(["definitely-not-a-real-binary-xyz"], tmp_path)


@pytest.mark.parametrize("bad", ["--public", "-x", "; rm -rf /", "a b",
                                 "owner/repo/extra", "", "owner/"])
def test_push_rejects_malformed_repo(tmp_path, bad):
    # validation happens before any subprocess, so no mocking needed
    with pytest.raises(vcs.VcsError, match="invalid repo"):
        vcs.push_github(tmp_path, bad)


def test_push_accepts_valid_repo_name(tmp_path, monkeypatch):
    calls = _record(monkeypatch)               # no origin -> create path
    monkeypatch.setattr(vcs.shutil, "which", lambda b: f"/usr/bin/{b}")
    vcs.push_github(tmp_path, "owner/my-repo.1")   # must not raise
    assert any(c[:1] == ["gh"] for c in calls)


def _write_manifest(tmp_path, **fields):
    import json
    (tmp_path / "manifest.json").write_text(
        json.dumps(fields, indent=2, sort_keys=True) + "\n")


def test_ensure_git_if_changed_skips_timestamp_only_but_commits_real_change(tmp_path):
    import subprocess
    _write_manifest(tmp_path, exported_at="T1", counts={"agents": 1})
    assert vcs.ensure_git(tmp_path, "s1", paths=["manifest.json"], if_changed=True) is True
    # only the timestamp moved -> no commit
    _write_manifest(tmp_path, exported_at="T2", counts={"agents": 1})
    assert vcs.ensure_git(tmp_path, "s2", paths=["manifest.json"], if_changed=True) is False
    # a real change (counts) -> commit
    _write_manifest(tmp_path, exported_at="T3", counts={"agents": 2})
    assert vcs.ensure_git(tmp_path, "s3", paths=["manifest.json"], if_changed=True) is True
    n = subprocess.run(["git", "-C", str(tmp_path), "rev-list", "--count", "HEAD"],
                       capture_output=True, text=True).stdout.strip()
    assert n == "2"     # s1 + s3 only (s2 skipped)


def test_github_repo_exists_true_false_and_validates(monkeypatch):
    monkeypatch.setattr(vcs.shutil, "which", lambda b: f"/usr/bin/{b}")
    monkeypatch.setattr(vcs, "_run", lambda args, cwd: "")          # gh repo view ok
    assert vcs.github_repo_exists("o/r") is True

    def boom(args, cwd):
        raise vcs.VcsError("not found")
    monkeypatch.setattr(vcs, "_run", boom)
    assert vcs.github_repo_exists("o/r") is False

    with pytest.raises(vcs.VcsError, match="invalid repo"):
        vcs.github_repo_exists("--evil")


def test_ensure_clone_clones_into_empty_dir(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(vcs.shutil, "which", lambda b: f"/usr/bin/{b}")
    monkeypatch.setattr(vcs, "_run", lambda args, cwd: calls.append(args) or "")
    assert vcs.ensure_clone("o/r", tmp_path / "clone") is True
    assert any(c[:3] == ["gh", "repo", "clone"] for c in calls)


def test_ensure_clone_noop_when_already_that_clone(tmp_path, monkeypatch):
    dest = tmp_path / "c"
    (dest / ".git").mkdir(parents=True)
    monkeypatch.setattr(vcs, "_run",
                        lambda args, cwd: "https://github.com/o/r.git"
                        if args[:2] == ["git", "remote"] else "")
    assert vcs.ensure_clone("o/r", dest) is False


def test_ensure_clone_refuses_nonempty_non_clone(tmp_path):
    dest = tmp_path / "d"
    dest.mkdir()
    (dest / "x").write_text("hi")
    with pytest.raises(vcs.VcsError, match="non-empty"):
        vcs.ensure_clone("o/r", dest)


def test_ensure_clone_refuses_same_name_different_owner(tmp_path, monkeypatch):
    # An existing clone of EVIL/r must NOT be treated as the right clone for good/r.
    dest = tmp_path / "c"
    (dest / ".git").mkdir(parents=True)
    monkeypatch.setattr(vcs, "_run",
                        lambda args, cwd: "https://github.com/EVIL/r.git"
                        if args[:2] == ["git", "remote"] else "")
    with pytest.raises(vcs.VcsError, match="refusing"):
        vcs.ensure_clone("good/r", dest)


def test_norm_repo_forms():
    assert vcs._norm_repo("https://github.com/Owner/Repo.git") == "owner/repo"
    assert vcs._norm_repo("git@github.com:Owner/Repo.git") == "owner/repo"
    assert vcs._norm_repo("owner/repo") == "owner/repo"
    assert vcs._norm_repo("repo") == "repo"            # bare -> never matches owner/repo


def test_ensure_git_commits_resource_deletions(tmp_path):
    import shutil as _sh
    import subprocess
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "a1.json").write_text("{}\n")
    (tmp_path / "manifest.json").write_text("{}\n")
    vcs.ensure_git(tmp_path, "s1", paths=["agents", "manifest.json"])

    # per-file: a1 removed, a2 added -> deletion must be committed
    (tmp_path / "agents" / "a1.json").unlink()
    (tmp_path / "agents" / "a2.json").write_text("{}\n")
    vcs.ensure_git(tmp_path, "s2", paths=["agents", "manifest.json"])

    def tracked():
        return subprocess.run(["git", "-C", str(tmp_path), "ls-files"],
                              capture_output=True, text=True).stdout
    assert "agents/a2.json" in tracked() and "agents/a1.json" not in tracked()

    # whole-type: agents/ removed entirely -> all of it leaves the committed tree
    _sh.rmtree(tmp_path / "agents")
    vcs.ensure_git(tmp_path, "s3", paths=["agents", "manifest.json"])
    assert "agents/" not in tracked()


def test_ensure_identity_does_not_clobber_global_name(tmp_path, monkeypatch):
    # Force the edge case: a name is configured but no email. The fix must set ONLY a
    # local email fallback and leave the name untouched.
    import subprocess
    empty = tmp_path / "gitconfig"
    empty.write_text("")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(empty))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "--local", "user.name", "Existing User"],
                   cwd=tmp_path, check=True)
    (tmp_path / "a.json").write_text("{}\n")
    vcs.ensure_git(tmp_path, "snap")

    def cfg(key):
        return subprocess.run(["git", "config", key], cwd=tmp_path,
                              capture_output=True, text=True).stdout.strip()
    assert cfg("user.name") == "Existing User"      # preserved, NOT clobbered
    assert cfg("user.email") == "cap@localhost"     # only the missing email got a fallback
