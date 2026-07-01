from __future__ import annotations

import os
import pathlib
import tomllib
from dataclasses import dataclass


class ConfigError(Exception):
    """Raised when the config file is missing, malformed, or incomplete."""


@dataclass(frozen=True)
class Settings:
    workspace_id: str
    region: str
    profile: str


def default_config_path() -> pathlib.Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return pathlib.Path(base) / "claude-platform" / "config.toml"


def load_settings(
    profile: str | None = None, config_path: pathlib.Path | None = None
) -> Settings:
    path = config_path or default_config_path()
    if not path.exists():
        raise ConfigError(f"No config at {path}. Run `claude-platform init`.")
    data = tomllib.loads(path.read_text())
    name = profile or data.get("default_profile")
    if not name:
        raise ConfigError("No profile given and no default_profile in config.")
    profiles = data.get("profiles", {})
    if name not in profiles:
        raise ConfigError(f"profile '{name}' not found in {path}.")
    p = profiles[name]
    for key in ("workspace_id", "region"):
        if not p.get(key):
            raise ConfigError(f"profile '{name}' is missing required key: {key}")
    return Settings(workspace_id=p["workspace_id"], region=p["region"], profile=name)


_TEMPLATE = '''\
# claude-platform config. AWS credentials are NOT stored here — they resolve
# from your ~/.aws credential chain (SigV4). Only workspace + region live here.
default_profile = "aws"

[profiles.aws]
workspace_id = "wrkspc_REPLACE_ME"
region = "us-east-1"
'''


def write_template(path: pathlib.Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_TEMPLATE)
