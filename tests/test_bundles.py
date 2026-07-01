import io
import types
import zipfile
from unittest.mock import MagicMock

import pytest
import typer

from claude_platform.bundles import safe_extract, skill_zip


def _zip(*entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, body in entries:
            z.writestr(name, body)
    return zipfile.ZipFile(io.BytesIO(buf.getvalue()))


def test_safe_extract_writes_members(tmp_path):
    names = safe_extract(_zip(("a/b.txt", "hi"), ("a/c.txt", "yo")), tmp_path / "out")
    assert set(names) == {"a/b.txt", "a/c.txt"}
    assert (tmp_path / "out" / "a" / "b.txt").read_text() == "hi"


def test_safe_extract_rejects_zip_slip(tmp_path):
    with pytest.raises(typer.BadParameter):
        safe_extract(_zip(("../escape.txt", "pwned")), tmp_path / "out")
    assert not (tmp_path / "escape.txt").exists()   # nothing written outside dest


def _client(latest="170001"):
    versions = MagicMock(spec=["download"])
    resp = MagicMock()
    resp.read.return_value = b"ZIPBYTES"
    versions.download.return_value = resp
    skills = MagicMock()
    skills.retrieve.return_value = types.SimpleNamespace(latest_version=latest)
    skills.versions = versions
    return types.SimpleNamespace(beta=types.SimpleNamespace(skills=skills)), skills, versions


def test_skill_zip_resolves_latest_when_no_version():
    client, skills, versions = _client(latest="9")
    ver, data = skill_zip(client, "skill_1", None)
    assert ver == "9" and data == b"ZIPBYTES"
    skills.retrieve.assert_called_once_with("skill_1")
    versions.download.assert_called_once_with("9", skill_id="skill_1")


def test_skill_zip_explicit_version_skips_retrieve():
    client, skills, versions = _client()
    ver, data = skill_zip(client, "skill_1", "5")
    assert ver == "5"
    skills.retrieve.assert_not_called()
    versions.download.assert_called_once_with("5", skill_id="skill_1")
