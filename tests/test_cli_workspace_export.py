import io
import json
import types
import zipfile
from unittest.mock import MagicMock

from typer.testing import CliRunner
import claude_platform.cli as climod
from claude_platform.cli import app

runner = CliRunner()


def _patch_client(monkeypatch, fake):
    monkeypatch.setattr(climod, "load_settings", lambda profile=None: types.SimpleNamespace(
        workspace_id="wrkspc_x", region="us-east-1", profile="aws"))
    monkeypatch.setattr(climod, "build_client", lambda settings: fake)


def _zip_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("fit-score/SKILL.md", "---\nname: fit-score\n---\nScore fit.\n")
        z.writestr("fit-score/ref.md", "notes\n")
    return buf.getvalue()


def _fake():
    agent = types.SimpleNamespace(model_dump=lambda: {"id": "agent_1", "name": "career-copilot"})
    agent_full = types.SimpleNamespace(model_dump=lambda: {
        "id": "agent_1", "name": "career-copilot", "system": "be helpful", "tools": []})
    ver = types.SimpleNamespace(model_dump=lambda: {"version": 1})
    agents = MagicMock()
    agents.list.return_value = [agent]
    agents.retrieve.return_value = agent_full
    agents.versions = MagicMock()
    agents.versions.list.return_value = [ver]

    skill = types.SimpleNamespace(model_dump=lambda: {"id": "skill_1", "display_title": "Fit Score"})
    skills = MagicMock()
    skills.list.return_value = [skill]
    skills.retrieve.return_value = types.SimpleNamespace(latest_version="170001")
    resp = MagicMock()
    resp.read.return_value = _zip_bytes()
    skills.versions = MagicMock()
    skills.versions.download.return_value = resp

    # credential carries a sensitive-looking field to prove redaction
    cred = types.SimpleNamespace(model_dump=lambda: {
        "id": "cred_1", "display_name": "mcp", "secret_token": "shh", "auth": {"type": "oauth"}})
    vault = types.SimpleNamespace(model_dump=lambda: {"id": "vault_1", "display_name": "v"})
    vaults = MagicMock()
    vaults.list.return_value = [vault]
    vaults.credentials = MagicMock()
    vaults.credentials.list.return_value = [cred]

    store = types.SimpleNamespace(model_dump=lambda: {"id": "store_1", "name": "mem"})
    memory_stores = MagicMock()
    memory_stores.list.return_value = [store]
    env = types.SimpleNamespace(model_dump=lambda: {"id": "env_1", "name": "e"})
    environments = MagicMock()
    environments.list.return_value = [env]
    deployments = MagicMock()
    deployments.list.side_effect = RuntimeError("API error: Error code: 404")  # no deployments surface

    beta = types.SimpleNamespace(agents=agents, skills=skills, vaults=vaults,
                                 memory_stores=memory_stores, environments=environments,
                                 deployments=deployments)
    return types.SimpleNamespace(beta=beta)


def test_export_writes_full_tree(tmp_path, monkeypatch):
    _patch_client(monkeypatch, _fake())
    out = tmp_path / "ws"
    result = runner.invoke(app, ["workspace", "export", str(out)])
    assert result.exit_code == 0, result.output

    agent = json.loads((out / "agents" / "agent_1.json").read_text())
    assert agent["agent"]["id"] == "agent_1"
    assert agent["agent"]["system"] == "be helpful"      # full config (from retrieve)
    assert agent["versions"][0]["version"] == 1

    assert json.loads((out / "skills" / "skill_1" / "skill.json").read_text())[
        "display_title"] == "Fit Score"
    assert (out / "skills" / "skill_1" / "bundle" / "fit-score" / "SKILL.md").read_text().startswith("---")
    assert (out / "skills" / "skill_1" / "bundle" / "fit-score" / "ref.md").exists()

    assert (out / "memory-stores" / "store_1.json").exists()
    assert (out / "environments" / "env_1.json").exists()


def test_export_redacts_secrets(tmp_path, monkeypatch):
    _patch_client(monkeypatch, _fake())
    out = tmp_path / "ws"
    result = runner.invoke(app, ["workspace", "export", str(out)])
    assert result.exit_code == 0, result.output
    v = json.loads((out / "vaults" / "vault_1.json").read_text())
    cred = v["credentials"][0]
    assert cred["secret_token"] == "***REDACTED***"      # sensitive value masked
    assert cred["display_name"] == "mcp"                 # non-sensitive preserved
    assert cred["auth"] == {"type": "oauth"}
    # and no raw secret anywhere in the file
    assert "shh" not in (out / "vaults" / "vault_1.json").read_text()


def test_export_is_fault_isolated_and_manifest_counts(tmp_path, monkeypatch):
    _patch_client(monkeypatch, _fake())
    out = tmp_path / "ws"
    result = runner.invoke(app, ["--json", "workspace", "export", str(out)])
    assert result.exit_code == 0, result.output      # deployments 404 must NOT fail the export
    m = json.loads((out / "manifest.json").read_text())
    assert m["counts"] == {"agents": 1, "skills": 1, "vaults": 1,
                           "memory_stores": 1, "environments": 1, "deployments": 0}
    assert any(e.startswith("deployments:") for e in m["errors"])
    assert m["workspace_id"] == "wrkspc_x" and m["region"] == "us-east-1"
    # stdout (auto-JSON under non-TTY) echoes the manifest
    assert json.loads(result.output)["counts"]["agents"] == 1


def _empty():
    m = MagicMock()
    m.list.return_value = []
    return m


def test_export_redacts_agent_freeform_secrets(tmp_path, monkeypatch):
    # Defence-in-depth: an agent's free-form fields (system prompt, metadata, MCP URL)
    # must be scrubbed even though they're config the API returns verbatim on read.
    agent = types.SimpleNamespace(model_dump=lambda: {"id": "agent_1", "name": "a"})
    agent_full = types.SimpleNamespace(model_dump=lambda: {
        "id": "agent_1", "name": "a",
        "system": "Authenticate with olo_agent_sk_LIVEKEY1234567890 before calling tools.",
        "metadata": {"deploy_token": "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "env": "prod"},
        "mcp_servers": [{"type": "url",
                         "url": "https://mcp.example.com/sse?token=supersecretvalue123"}],
        "tools": []})
    agents = MagicMock()
    agents.list.return_value = [agent]
    agents.retrieve.return_value = agent_full
    agents.versions = MagicMock()
    agents.versions.list.return_value = []
    beta = types.SimpleNamespace(agents=agents, skills=_empty(), vaults=_empty(),
                                 memory_stores=_empty(), environments=_empty(),
                                 deployments=_empty())
    _patch_client(monkeypatch, types.SimpleNamespace(beta=beta))
    out = tmp_path / "ws"
    result = runner.invoke(app, ["workspace", "export", str(out)])
    assert result.exit_code == 0, result.output
    txt = (out / "agents" / "agent_1.json").read_text()
    assert "olo_agent_sk_LIVEKEY" not in txt        # token in system prompt scrubbed
    assert "ghp_aaaa" not in txt                    # token in metadata (sensitive key) masked
    assert "supersecretvalue123" not in txt         # token in MCP URL query scrubbed
    assert "REDACTED" in txt
    a = json.loads(txt)
    assert a["agent"]["metadata"]["env"] == "prod"  # non-secret field preserved


def test_no_skill_bundles_flag_skips_download(tmp_path, monkeypatch):
    fake = _fake()
    _patch_client(monkeypatch, fake)
    out = tmp_path / "ws"
    result = runner.invoke(app, ["workspace", "export", str(out), "--no-skill-bundles"])
    assert result.exit_code == 0, result.output
    assert (out / "skills" / "skill_1" / "skill.json").exists()
    assert not (out / "skills" / "skill_1" / "bundle").exists()
    fake.beta.skills.versions.download.assert_not_called()


def test_export_git_commits_the_tree(tmp_path, monkeypatch):
    # --git uses real git locally (no network); the exported tree becomes a commit.
    _patch_client(monkeypatch, _fake())
    out = tmp_path / "ws"
    result = runner.invoke(app, ["--json", "workspace", "export", str(out), "--git"])
    assert result.exit_code == 0, result.output
    assert (out / ".git").is_dir()
    assert (out / ".gitignore").exists()
    assert json.loads(result.output)["committed"] is True


def test_export_git_only_commits_export_paths(tmp_path, monkeypatch):
    # A stray file already in DIR must NOT be committed — only the export's own paths.
    import subprocess
    _patch_client(monkeypatch, _fake())
    out = tmp_path / "ws"
    out.mkdir()
    (out / ".env").write_text("SECRET=shh\n")
    (out / "notes.txt").write_text("private notes\n")
    result = runner.invoke(app, ["--json", "workspace", "export", str(out), "--git"])
    assert result.exit_code == 0, result.output
    tracked = subprocess.run(["git", "-C", str(out), "ls-files"],
                             capture_output=True, text=True).stdout
    assert ".env" not in tracked and "notes.txt" not in tracked   # strays excluded
    assert "manifest.json" in tracked and "agents/agent_1.json" in tracked
    assert "shh" not in subprocess.run(["git", "-C", str(out), "show", "HEAD"],
                                       capture_output=True, text=True).stdout


def test_export_preserves_section_when_its_list_fails(tmp_path, monkeypatch):
    # A transient failure in agents.list() on a re-export must NOT erase the previously
    # exported agents/ (the section is cleared only AFTER a successful list).
    out = tmp_path / "ws"
    _patch_client(monkeypatch, _fake())
    runner.invoke(app, ["workspace", "export", str(out)])
    assert (out / "agents" / "agent_1.json").exists()

    fake2 = _fake()
    fake2.beta.agents.list.side_effect = RuntimeError("transient 503")
    _patch_client(monkeypatch, fake2)
    result = runner.invoke(app, ["--json", "workspace", "export", str(out)])
    assert result.exit_code == 0, result.output
    assert (out / "agents" / "agent_1.json").exists()      # preserved, not erased
    m = json.loads((out / "manifest.json").read_text())
    assert any(e.startswith("agents:") for e in m["errors"])


def test_export_refuses_to_clobber_non_export_directory(tmp_path, monkeypatch):
    # A real project dir that merely has an `agents/` (not a cap export, not a git repo)
    # must NOT be wiped — export refuses rather than rmtree real user files.
    _patch_client(monkeypatch, _fake())
    out = tmp_path / "myproj"
    (out / "agents").mkdir(parents=True)
    (out / "agents" / "lead.md").write_text("hand-written agent\n")
    result = runner.invoke(app, ["workspace", "export", str(out)])
    assert result.exit_code != 0                              # refused
    assert (out / "agents" / "lead.md").exists()              # NOT destroyed


def test_export_if_changed_skips_timestamp_only_commit(tmp_path, monkeypatch):
    import subprocess
    _patch_client(monkeypatch, _fake())
    out = tmp_path / "ws"
    r1 = runner.invoke(app, ["--json", "workspace", "export", str(out), "--git"])
    assert r1.exit_code == 0 and json.loads(r1.output)["committed"] is True
    # same workspace, --if-changed -> only the timestamp differs -> no new commit
    r2 = runner.invoke(app, ["--json", "workspace", "export", str(out), "--git", "--if-changed"])
    assert r2.exit_code == 0, r2.output
    assert json.loads(r2.output)["committed"] is False
    n = subprocess.run(["git", "-C", str(out), "rev-list", "--count", "HEAD"],
                       capture_output=True, text=True).stdout.strip()
    assert n == "1"     # still just the first commit


def test_export_clears_stale_resource_dirs(tmp_path, monkeypatch):
    # A re-export must reflect the CURRENT workspace: a resource that disappeared between
    # runs (here agent_1 -> agent_2) must be removed from the export, not linger.
    out = tmp_path / "ws"
    _patch_client(monkeypatch, _fake())                          # agent_1
    runner.invoke(app, ["workspace", "export", str(out)])
    assert (out / "agents" / "agent_1.json").exists()

    agent2 = types.SimpleNamespace(model_dump=lambda: {"id": "agent_2", "name": "b"})
    a2 = MagicMock()
    a2.list.return_value = [agent2]
    a2.retrieve.return_value = agent2
    a2.versions = MagicMock()
    a2.versions.list.return_value = []
    beta = types.SimpleNamespace(agents=a2, skills=_empty(), vaults=_empty(),
                                 memory_stores=_empty(), environments=_empty(),
                                 deployments=_empty())
    _patch_client(monkeypatch, types.SimpleNamespace(beta=beta))
    runner.invoke(app, ["workspace", "export", str(out)])
    assert (out / "agents" / "agent_2.json").exists()
    assert not (out / "agents" / "agent_1.json").exists()        # stale agent removed


def test_export_push_is_private_by_default(tmp_path, monkeypatch):
    import claude_platform.vcs as vcsmod
    _patch_client(monkeypatch, _fake())
    captured = {}
    monkeypatch.setattr(vcsmod, "github_repo_exists", lambda repo: False)   # new-repo path
    monkeypatch.setattr(vcsmod, "ensure_git",
                        lambda dest, msg, paths=None, if_changed=False: True)

    def fake_push(dest, repo, private=True):
        captured["call"] = (str(dest), repo, private)
        return "https://github.com/o/r.git"

    monkeypatch.setattr(vcsmod, "push_github", fake_push)
    out = tmp_path / "ws"
    result = runner.invoke(app, ["--json", "workspace", "export", str(out), "--push", "o/r"])
    assert result.exit_code == 0, result.output
    assert captured["call"][1] == "o/r" and captured["call"][2] is True   # private by default
    assert json.loads(result.output)["repo_url"] == "https://github.com/o/r.git"


def test_export_push_public_flag(tmp_path, monkeypatch):
    import claude_platform.vcs as vcsmod
    _patch_client(monkeypatch, _fake())
    captured = {}
    monkeypatch.setattr(vcsmod, "github_repo_exists", lambda repo: False)
    monkeypatch.setattr(vcsmod, "ensure_git",
                        lambda dest, msg, paths=None, if_changed=False: True)
    monkeypatch.setattr(vcsmod, "push_github",
                        lambda dest, repo, private=True: captured.update(private=private) or "u")
    out = tmp_path / "ws"
    result = runner.invoke(app, ["workspace", "export", str(out), "--push", "o/r", "--public"])
    assert result.exit_code == 0, result.output
    assert captured["private"] is False                                    # --public honored


def test_export_push_existing_repo_clones_first(tmp_path, monkeypatch):
    # When the repo already exists, DIR is cloned from it before export so the push is a
    # fast-forward diff (not a divergent root commit).
    import claude_platform.vcs as vcsmod
    _patch_client(monkeypatch, _fake())
    calls = {}
    monkeypatch.setattr(vcsmod, "github_repo_exists", lambda repo: True)
    monkeypatch.setattr(vcsmod, "ensure_clone",
                        lambda repo, dest: calls.setdefault("clone", (repo, str(dest))))
    monkeypatch.setattr(vcsmod, "ensure_git",
                        lambda dest, msg, paths=None, if_changed=False: True)
    monkeypatch.setattr(vcsmod, "push_github",
                        lambda dest, repo, private=True: "https://github.com/o/r.git")
    out = tmp_path / "ws"
    result = runner.invoke(app, ["workspace", "export", str(out), "--push", "o/r"])
    assert result.exit_code == 0, result.output
    assert calls["clone"] == ("o/r", str(out))             # cloned before exporting
