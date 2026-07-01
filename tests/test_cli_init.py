from typer.testing import CliRunner
from claude_platform.cli import app

runner = CliRunner()

def test_init_writes_template(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0
    cfg = tmp_path / "claude-platform" / "config.toml"
    assert cfg.exists() and "[profiles.aws]" in cfg.read_text()

def test_init_refuses_overwrite(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["init"])
    assert result.exit_code != 0
    assert "exists" in result.output.lower()

def test_help_runs():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
