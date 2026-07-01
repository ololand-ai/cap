"""Whole-workspace export: snapshot the control plane to a git-ready JSON tree.

Read-only. Reuses the audited Zip-Slip-guarded extractor from `bundles`.

Secret handling — the load-bearing guarantee is the API contract: vault credential
secret VALUES are write-only and are never returned on read, so they cannot reach the
export. On top of that, EVERY JSON record goes through `_redact` (centralised in
`_write_json` so no section can forget it): it masks values under sensitive-looking KEY
names AND scrubs known secret token shapes / URL-embedded credentials out of free-form
string values (system prompts, MCP URLs, metadata). The value scrub is best-effort
defence-in-depth, NOT a guarantee against an arbitrary secret a user pasted into a
prompt. Skill *bundle* files are written verbatim (they are the user's authored content).
"""
from __future__ import annotations

import io
import json
import pathlib
import re
import shutil
import zipfile
from datetime import datetime, timezone

from claude_platform.bundles import safe_extract, skill_zip

# Keys whose VALUES are masked if they ever appear in exported metadata. The API does
# not return credential secrets on read; this is belt-and-suspenders so a future API
# change can't silently write a secret into a git repo.
_SENSITIVE = ("secret", "token", "password", "passwd", "api_key", "apikey",
              "private_key", "privatekey", "bearer", "client_secret")
_REDACTED = "***REDACTED***"

# Known secret token shapes + URL-embedded credentials, for value-level scrubbing of
# free-form fields (system prompts, MCP URLs, metadata). Best-effort defence-in-depth —
# the real guarantee is the API contract (secrets are write-only, never returned on read).
_TOKEN_RE = re.compile(
    r"(sk-ant-[A-Za-z0-9_-]{6,}|olo_agent_sk_[A-Za-z0-9]{6,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|gh[opsu]_[A-Za-z0-9]{20,}|"
    r"sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{12,}|xox[abpos]-[A-Za-z0-9-]{8,}|"
    r"AIza[A-Za-z0-9_-]{20,})")
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}")
_URLCRED_RE = re.compile(
    r"(?i)([?&](?:token|api[_-]?key|access[_-]?token|auth|key|password|secret)=)[^&\s\"']+")
_USERINFO_RE = re.compile(r"(://)[^/\s:@]+:[^/\s@]+@")


def _scrub_str(s: str) -> str:
    s = _TOKEN_RE.sub(_REDACTED, s)
    s = _BEARER_RE.sub("bearer " + _REDACTED, s)
    s = _URLCRED_RE.sub(r"\1" + _REDACTED, s)
    s = _USERINFO_RE.sub(r"\1" + _REDACTED + "@", s)
    return s


_METADATA_RESOURCES = (
    # (summary key, CLI/dir name, SDK beta attribute)
    ("memory_stores", "memory-stores", "memory_stores"),
    ("environments", "environments", "environments"),
    ("deployments", "deployments", "deployments"),
)

# Top-level paths export_workspace writes. The publisher (`--git`/`--push`) stages ONLY
# these (+ .gitignore), so a file already sitting in the target dir is never committed.
EXPORT_TOPLEVEL = ("agents", "skills", "vaults", "memory-stores",
                   "environments", "deployments", "manifest.json")


def _dump(obj):
    return obj.model_dump() if hasattr(obj, "model_dump") else obj


def _redact(obj):
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and any(s in k.lower() for s in _SENSITIVE) and v not in (None, "", {}, []):
                out[k] = _REDACTED
            else:
                out[k] = _redact(v)
        return out
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    if isinstance(obj, str):
        return _scrub_str(obj)
    return obj


def _write_json(path: pathlib.Path, obj) -> None:
    # Redact centrally so every record written to disk is covered — no section can forget.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_redact(obj), indent=2, default=str, sort_keys=True) + "\n")


def _safe_id(d: dict, fallback: str) -> str:
    """A filesystem-safe identifier for a resource record."""
    rid = d.get("id") or d.get("version") or fallback
    return str(rid).replace("/", "_")


def export_workspace(client, dest, *, workspace_id: str = "", region: str = "",
                     include_skill_bundles: bool = True, now=None) -> dict:
    """Export the workspace's config resources under `dest`. Returns the manifest dict.

    Every section is fault-isolated: a failure (e.g. a workspace with no deployments
    surface -> 404) is recorded in `errors` and the export continues. Never raises for
    a per-resource fetch failure; only a failure to create `dest` propagates.
    """
    dest = pathlib.Path(dest).expanduser()
    dest.mkdir(parents=True, exist_ok=True)
    counts = {"agents": 0, "skills": 0, "vaults": 0,
              "memory_stores": 0, "environments": 0, "deployments": 0}
    errors: list[str] = []

    def _err(section: str, exc: Exception) -> None:
        errors.append(f"{section}: {type(exc).__name__}: {exc}")

    def _clear(p: pathlib.Path) -> None:
        if p.is_dir():
            try:
                shutil.rmtree(p)
            except OSError as exc:  # noqa: BLE001 - recorded, export continues
                _err(f"clear/{p.name}", exc)

    # Faithful current-state snapshot: each section clears its previously-exported dir
    # AFTER a successful list() (below), so a transient list failure never erases that
    # section. manifest.json + bundles are rewritten below; non-export files in `dest`
    # (e.g. README.md) are untouched.
    # SAFETY: refuse to touch managed-named dirs in an arbitrary non-empty directory —
    # only a prior cap export (manifest.json) or a git repo (.git) is clearable (both make
    # the deletion recoverable), so we never clobber a real agents/ or skills/ project.
    _managed = [dest / n for n in EXPORT_TOPLEVEL if n != "manifest.json"]
    if any(p.is_dir() for p in _managed) and not (
            (dest / "manifest.json").exists() or (dest / ".git").is_dir()):
        raise ValueError(
            f"{dest} already contains agent/skill/etc. directories but is not a prior cap "
            "export or a git repo — refusing to overwrite it. Export to an empty or "
            "dedicated directory.")

    beta = client.beta

    # --- agents: full config + version history ---
    try:
        agents = list(beta.agents.list())
        _clear(dest / "agents")
        for i, a in enumerate(agents):
            d = _dump(a)
            aid = _safe_id(d, f"agent-{i}")
            record = {"agent": _dump(beta.agents.retrieve(d.get("id")))}
            try:
                record["versions"] = [_dump(v) for v in beta.agents.versions.list(d.get("id"))]
            except Exception as exc:  # noqa: BLE001
                _err(f"agents/{aid}/versions", exc)
            _write_json(dest / "agents" / f"{aid}.json", record)
            counts["agents"] += 1
    except Exception as exc:  # noqa: BLE001
        _err("agents", exc)

    # --- skills: metadata + (optionally) the downloaded bundle ---
    try:
        skills = list(beta.skills.list())
        _clear(dest / "skills")
        for i, s in enumerate(skills):
            d = _dump(s)
            sid = _safe_id(d, f"skill-{i}")
            _write_json(dest / "skills" / sid / "skill.json", d)
            if include_skill_bundles:
                try:
                    _, data = skill_zip(client, d.get("id"), None)
                    safe_extract(zipfile.ZipFile(io.BytesIO(data)),
                                 dest / "skills" / sid / "bundle")
                except Exception as exc:  # noqa: BLE001
                    _err(f"skills/{sid}/bundle", exc)
            counts["skills"] += 1
    except Exception as exc:  # noqa: BLE001
        _err("skills", exc)

    # --- vaults: metadata + credentials metadata (secrets are write-only -> never present) ---
    try:
        vaults = list(beta.vaults.list())
        _clear(dest / "vaults")
        for i, v in enumerate(vaults):
            d = _dump(v)
            vid = _safe_id(d, f"vault-{i}")
            creds = []
            try:
                creds = [_dump(c) for c in beta.vaults.credentials.list(d.get("id"))]
            except Exception as exc:  # noqa: BLE001
                _err(f"vaults/{vid}/credentials", exc)
            # _write_json redacts the whole record centrally.
            _write_json(dest / "vaults" / f"{vid}.json", {
                "vault": d,
                "credentials": creds,
                "_note": "secret values are write-only and are not exported",
            })
            counts["vaults"] += 1
    except Exception as exc:  # noqa: BLE001
        _err("vaults", exc)

    # --- metadata-only resources ---
    for key, dirname, attr in _METADATA_RESOURCES:
        try:
            sub = getattr(beta, attr)
            items = list(sub.list())
            _clear(dest / dirname)
            n = 0
            for i, it in enumerate(items):
                d = _dump(it)
                _write_json(dest / dirname / f"{_safe_id(d, f'{key}-{i}')}.json", d)
                n += 1
            counts[key] = n
        except Exception as exc:  # noqa: BLE001
            _err(key, exc)

    manifest = {
        "workspace_id": workspace_id,
        "region": region,
        "exported_at": (now or datetime.now(timezone.utc)).isoformat(),
        "counts": counts,
        "errors": errors,
        "note": ("Vault credential secret values are write-only and are NOT exported. "
                 "Re-inject secrets from your own secret manager when re-creating. "
                 "Resource ids are per-account; re-creating mints new ids."),
    }
    _write_json(dest / "manifest.json", manifest)
    # `out` is the local export path — useful to the caller (git ops, output) but NOT part
    # of the snapshot: it's machine-specific noise that would pollute every diff and defeat
    # --if-changed. So it's returned but never written to the committed manifest.
    return {**manifest, "out": str(dest)}
