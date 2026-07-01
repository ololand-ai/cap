import pathlib
import pytest
from claude_platform.config import (
    ConfigError, Settings, load_settings, write_template, default_config_path,
)

def _write(tmp_path: pathlib.Path, text: str) -> pathlib.Path:
    p = tmp_path / "config.toml"
    p.write_text(text)
    return p

def test_loads_default_profile(tmp_path):
    cfg = _write(tmp_path, '''
default_profile = "aws"
[profiles.aws]
workspace_id = "wrkspc_123"
region = "us-east-1"
''')
    s = load_settings(config_path=cfg)
    assert s == Settings(workspace_id="wrkspc_123", region="us-east-1", profile="aws")

def test_named_profile_overrides_default(tmp_path):
    cfg = _write(tmp_path, '''
default_profile = "aws"
[profiles.aws]
workspace_id = "wrkspc_a"
region = "us-east-1"
[profiles.staging]
workspace_id = "wrkspc_b"
region = "us-west-2"
''')
    s = load_settings(profile="staging", config_path=cfg)
    assert s.workspace_id == "wrkspc_b" and s.region == "us-west-2"

def test_missing_file_raises(tmp_path):
    with pytest.raises(ConfigError, match="No config"):
        load_settings(config_path=tmp_path / "nope.toml")

def test_missing_profile_raises(tmp_path):
    cfg = _write(tmp_path, 'default_profile = "aws"\n[profiles.other]\nworkspace_id="x"\nregion="y"\n')
    with pytest.raises(ConfigError, match="profile 'aws'"):
        load_settings(config_path=cfg)

def test_missing_required_key_raises(tmp_path):
    cfg = _write(tmp_path, 'default_profile = "aws"\n[profiles.aws]\nworkspace_id=""\nregion="us-east-1"\n')
    with pytest.raises(ConfigError, match="workspace_id"):
        load_settings(config_path=cfg)

def test_default_config_path_is_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert default_config_path() == tmp_path / "claude-platform" / "config.toml"

def test_write_template_is_loadable_after_edit(tmp_path):
    p = tmp_path / "claude-platform" / "config.toml"
    write_template(p)
    text = p.read_text()
    assert "[profiles.aws]" in text and "workspace_id" in text
