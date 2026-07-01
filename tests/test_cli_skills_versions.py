import io
import json
import types
import zipfile
from unittest.mock import MagicMock

from typer.testing import CliRunner

import claude_platform.cli as climod
from claude_platform.cli import app

runner = CliRunner()


def _patch_client(monkeypatch, fake_client):
    monkeypatch.setattr(climod, "load_settings", lambda profile=None: types.SimpleNamespace(
        workspace_id="wrkspc_x", region="us-east-1", profile="aws"))
    monkeypatch.setattr(climod, "build_client", lambda settings: fake_client)


def _fake():
    ver = types.SimpleNamespace(model_dump=lambda: {"version": 2, "created_at": "2026-06-23"})
    versions = MagicMock()
    versions.create.return_value = ver
    versions.list.return_value = [ver]
    skills = types.SimpleNamespace(versions=versions)
    return types.SimpleNamespace(beta=types.SimpleNamespace(skills=skills)), versions


def _skill_folder(tmp_path):
    d = tmp_path / "scout"
    d.mkdir()
    (d / "SKILL.md").write_text("---\nname: scout\n---\nScout roles.\n")
    (d / "reference.md").write_text("notes\n")
    (d / "__pycache__").mkdir()
    (d / "__pycache__" / "junk.pyc").write_bytes(b"\x00")  # must be excluded
    return d


def test_skills_update_bundles_folder_and_calls_versions_create(tmp_path, monkeypatch):
    fake, versions = _fake()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(app, ["--json", "skills", "update", "skill_1", str(_skill_folder(tmp_path))])
    assert result.exit_code == 0, result.output
    versions.create.assert_called_once()
    args, kwargs = versions.create.call_args
    assert args[0] == "skill_1"
    names = [f[0] for f in kwargs["files"]]
    # every file nested under the top-level skill-folder name; SKILL.md present; pycache excluded
    assert "scout/SKILL.md" in names
    assert "scout/reference.md" in names
    assert not any("__pycache__" in n for n in names)
    assert json.loads(result.output)["version"] == 2


def test_skills_versions_create_is_an_alias_for_update(tmp_path, monkeypatch):
    fake, versions = _fake()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(
        app, ["--json", "skills", "versions", "create", "skill_1", str(_skill_folder(tmp_path))])
    assert result.exit_code == 0, result.output
    assert versions.create.call_args[0][0] == "skill_1"


def test_skills_versions_list_calls_sdk(monkeypatch):
    fake, versions = _fake()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(app, ["--json", "skills", "versions", "list", "skill_1"])
    assert result.exit_code == 0, result.output
    versions.list.assert_called_once_with("skill_1")
    assert json.loads(result.output)[0]["version"] == 2


def test_skills_update_requires_skill_md(tmp_path, monkeypatch):
    fake, versions = _fake()
    _patch_client(monkeypatch, fake)
    bad = tmp_path / "nope"
    bad.mkdir()
    (bad / "readme.txt").write_text("x")
    result = runner.invoke(app, ["--json", "skills", "update", "skill_1", str(bad)])
    assert result.exit_code != 0
    versions.create.assert_not_called()


def test_generic_skills_verbs_still_present(monkeypatch):
    # adding versioning must not clobber the generic list/get/create/delete commands
    result = runner.invoke(app, ["skills", "--help"])
    assert result.exit_code == 0
    for verb in ("list", "get", "create", "delete", "update", "versions", "show", "download"):
        assert verb in result.output


def _zip_bytes():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("scout/SKILL.md", "---\nname: scout\n---\nScout roles.\n")
        z.writestr("scout/references/sources.md", "ats list\n")
    return buf.getvalue()


def _fake_download(latest="170001"):
    """A client whose skills.versions.download returns a BinaryAPIResponse-like object
    (has .read() -> zip bytes), and whose skills.retrieve carries .latest_version."""
    versions = MagicMock()
    resp = MagicMock()
    resp.read.return_value = _zip_bytes()
    versions.download.return_value = resp
    skills = MagicMock()
    skills.retrieve.return_value = types.SimpleNamespace(latest_version=latest)
    skills.versions = versions
    return types.SimpleNamespace(beta=types.SimpleNamespace(skills=skills)), skills, versions


def test_skills_show_resolves_latest_and_prints_skill_md(monkeypatch):
    fake, skills, versions = _fake_download()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(app, ["--json", "skills", "show", "skill_1"])
    assert result.exit_code == 0, result.output
    skills.retrieve.assert_called_once_with("skill_1")            # resolved latest
    args, kwargs = versions.download.call_args
    assert args[0] == "170001" and kwargs["skill_id"] == "skill_1"
    out = json.loads(result.output)
    assert out["version"] == "170001"
    assert "Scout roles." in out["skill_md"]
    assert "scout/SKILL.md" in out["files"]


def test_skills_show_with_explicit_version_skips_retrieve(monkeypatch):
    fake, skills, versions = _fake_download()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(app, ["--json", "skills", "show", "skill_1", "--version", "9999"])
    assert result.exit_code == 0, result.output
    skills.retrieve.assert_not_called()
    assert versions.download.call_args[0][0] == "9999"


def test_skills_download_extracts_bundle(tmp_path, monkeypatch):
    fake, skills, versions = _fake_download()
    _patch_client(monkeypatch, fake)
    out = tmp_path / "dl"
    result = runner.invoke(app, ["--json", "skills", "download", "skill_1", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert (out / "scout" / "SKILL.md").read_text().startswith("---")
    assert (out / "scout" / "references" / "sources.md").exists()
    assert json.loads(result.output)["out"] == str(out)


def test_skills_download_rejects_zip_slip(tmp_path, monkeypatch):
    # a malicious bundle whose entry escapes the target dir must abort, not write outside it
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("../escape.md", "pwned\n")
    versions = MagicMock()
    resp = MagicMock()
    resp.read.return_value = buf.getvalue()
    versions.download.return_value = resp
    skills = MagicMock()
    skills.retrieve.return_value = types.SimpleNamespace(latest_version="1")
    skills.versions = versions
    fake = types.SimpleNamespace(beta=types.SimpleNamespace(skills=skills))
    _patch_client(monkeypatch, fake)
    out = tmp_path / "dl"
    result = runner.invoke(app, ["--json", "skills", "download", "skill_1", "--out", str(out)])
    assert result.exit_code != 0
    assert not (tmp_path / "escape.md").exists()   # nothing written to the parent


def _fake_get_delete():
    ver = types.SimpleNamespace(model_dump=lambda: {"version": "170001", "created_at": "2026-06-23"})
    versions = MagicMock(spec=["create", "list", "retrieve", "delete"])
    versions.retrieve.return_value = ver
    versions.delete.return_value = ver
    skills = types.SimpleNamespace(versions=versions)
    return types.SimpleNamespace(beta=types.SimpleNamespace(skills=skills)), versions


def test_versions_get_own_id_positional_parent_keyword(monkeypatch):
    fake, versions = _fake_get_delete()
    _patch_client(monkeypatch, fake)
    result = runner.invoke(
        app, ["--json", "skills", "versions", "get", "170001", "--skill", "skill_1"])
    assert result.exit_code == 0, result.output
    versions.retrieve.assert_called_once_with("170001", skill_id="skill_1")  # NOT .get


def test_versions_delete_gated_then_calls_sdk(monkeypatch):
    fake, versions = _fake_get_delete()
    _patch_client(monkeypatch, fake)
    blocked = runner.invoke(
        app, ["skills", "versions", "delete", "170001", "--skill", "skill_1"])
    assert blocked.exit_code == 4
    versions.delete.assert_not_called()
    ok = runner.invoke(
        app, ["--yes", "skills", "versions", "delete", "170001", "--skill", "skill_1"])
    assert ok.exit_code == 0, ok.output
    versions.delete.assert_called_once_with("170001", skill_id="skill_1")


def test_versions_subtyper_has_all_verbs(monkeypatch):
    result = runner.invoke(app, ["skills", "versions", "--help"])
    assert result.exit_code == 0
    for verb in ("create", "list", "get", "delete"):
        assert verb in result.output
