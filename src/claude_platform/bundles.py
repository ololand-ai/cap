from __future__ import annotations

import pathlib
import zipfile

import typer


def skill_zip(client, skill_id: str, version: str | None) -> tuple[str, bytes]:
    """(version, zip-bytes) for a skill version's content. Resolves the latest version
    when none is given. The metadata endpoints carry no content — this downloads the
    actual bundle (skills.versions.download returns a zip archive)."""
    if not version:
        version = client.beta.skills.retrieve(skill_id).latest_version
    resp = client.beta.skills.versions.download(version, skill_id=skill_id)
    data = resp.read() if hasattr(resp, "read") else resp.content
    return version, data


def safe_extract(zf: zipfile.ZipFile, dest: pathlib.Path) -> list[str]:
    """Extract every member of `zf` into `dest`, rejecting any entry whose path escapes
    `dest` (Zip Slip / path traversal). Returns the member names. zipfile.extractall
    already strips '..' since 3.6.2, but we don't rely on that implicit behaviour: a
    member resolving outside dest aborts the whole extraction rather than being silently
    rewritten."""
    dest = dest.resolve()
    names = zf.namelist()
    for name in names:
        target = (dest / name).resolve()
        if target != dest and dest not in target.parents:
            raise typer.BadParameter(f"refusing to extract entry outside {dest}: {name!r}")
    zf.extractall(dest)
    return names
