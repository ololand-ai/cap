from __future__ import annotations

import io
import mimetypes
import pathlib
import sys
import zipfile

import typer

from claude_platform import config
from claude_platform.bundles import safe_extract, skill_zip
from claude_platform.client import build_client
from claude_platform.config import load_settings
from claude_platform.errors import format_error
from claude_platform.render import render
from claude_platform.resources import (
    RESOURCES, Resource, Verb, IdClass, Payload, accessor,
)
from claude_platform.safety import check as safety_check
import json as _json

app = typer.Typer(no_args_is_help=True, help="Manage a Claude Platform on AWS workspace.")


@app.callback()
def main(
    ctx: typer.Context,
    profile: str | None = typer.Option(None, "--profile", help="Config profile to use."),
    json_out: bool = typer.Option(False, "--json", help="Emit raw JSON."),
    yes: bool = typer.Option(False, "--yes", help="Confirm destructive operations."),
) -> None:
    # Auto-JSON when stdout is not a terminal (piped / called by Claude Code),
    # so automated callers always get machine-readable output.
    effective_json = json_out or not sys.stdout.isatty()
    ctx.obj = {"profile": profile, "json": effective_json, "yes": yes}


@app.command()
def init(
    force: bool = typer.Option(False, "--force", help="Overwrite an existing config."),
) -> None:
    """Write a starter config to ~/.config/claude-platform/config.toml."""
    path = config.default_config_path()
    if path.exists() and not force:
        typer.echo(f"Config already exists at {path} (use --force to overwrite).")
        raise typer.Exit(2)
    config.write_template(path)
    typer.echo(f"Wrote {path}. Edit it to set your workspace_id and region.")


def _to_dict(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    return obj


# CLI verb -> SDK method name. The user-facing `get` subcommand maps onto the
# anthropic SDK's `retrieve` method (there is no `get` on beta.agents/sessions).
_SDK_METHOD = {"get": "retrieve"}


def _read_data(data: str | None) -> str | None:
    if data and data.startswith("@"):
        return pathlib.Path(data[1:]).read_text()
    return data


def _bundle_skill(folder: str) -> list[tuple[str, bytes, str]]:
    """Bundle a skill folder into API file tuples (path, bytes, mime). Requires a
    SKILL.md; every file is nested under one top-level dir named for the skill."""
    root = pathlib.Path(folder).expanduser()
    if not (root / "SKILL.md").is_file():
        raise typer.BadParameter(f"no SKILL.md in {root}")
    files: list[tuple[str, bytes, str]] = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            rel = f"{root.name}/{p.relative_to(root).as_posix()}"
            mime = mimetypes.guess_type(p.name)[0] or "text/markdown"
            files.append((rel, p.read_bytes(), mime))
    if not files:
        raise typer.BadParameter(f"no files found under {root}")
    return files


# ---------------------------------------------------------------------------
# Dispatcher: one id-chain dispatch for the whole resource tree.
# ---------------------------------------------------------------------------
def _run_node(ctx, path, verb: Verb, *, ident=None, ancestor_ids=None,
              data=None, folder=None):
    node = path[-1]
    ancestor_ids = ancestor_ids or {}
    opts = ctx.obj or {}
    # `target` is only consumed by the safety message. No PARENT_SCOPED verb is ever
    # destructive (destructive verbs are CHILD/SELF and always carry their own `ident`),
    # so the ancestor-id fallback is defensive-only — never hit for a gated op.
    target = ident or (next(iter(ancestor_ids.values()), None)) or node.name
    try:
        safety_check(verb.name, target, yes=opts.get("yes", False),
                     destructive=verb.destructive)
        settings = load_settings(profile=opts.get("profile"))
        client = build_client(settings)
        sdk = accessor(client, path)
        method = getattr(sdk, verb.sdk_method or _SDK_METHOD.get(verb.name, verb.name))

        anc = list(path[:-1])  # ancestors above this node, root..immediate-parent
        pos, kw = [], {}
        if verb.id_class is IdClass.PARENT_SCOPED:
            if anc:
                pos.append(ancestor_ids[anc[-1].parent_id_kw])      # immediate parent positional
                for a in anc[:-1]:                                  # higher ancestors keyword-only
                    kw[a.parent_id_kw] = ancestor_ids[a.parent_id_kw]
        elif verb.id_class in (IdClass.CHILD, IdClass.SELF):
            pos.append(ident)                                       # own id positional
            for a in anc:                                           # ALL ancestors keyword-only
                kw[a.parent_id_kw] = ancestor_ids[a.parent_id_kw]

        if verb.payload is Payload.JSON:
            kw.update(_json.loads(data) if data else {})
        elif verb.payload is Payload.SKILL_FOLDER:
            kw["files"] = _bundle_skill(folder)

        result = method(*pos, **kw)
        if verb.name == "list":
            result = list(result)
    except Exception as exc:  # noqa: BLE001 - mapped to exit codes
        msg, code = format_error(exc)
        if opts.get("json", False):
            typer.echo(_json.dumps({"error": msg, "exit_code": code}), err=True)
        else:
            typer.echo(msg, err=True)
        raise typer.Exit(code)

    payload = ([_to_dict(x) for x in result] if isinstance(result, list)
               else _to_dict(result))
    # Per-verb columns win when the verb's response model diverges from the node's
    # (e.g. work stats); otherwise inherit the node's columns.
    base_cols = list(verb.columns) if verb.columns else list(node.columns)
    if verb.payload is Payload.URL:
        # response holds a URL field; surface it in the columns so JSON+table both show it.
        cols = base_cols + [c for c in ("url", "enrollment_url") if c not in base_cols]
    else:
        cols = base_cols
    typer.echo(render(payload, as_json=opts.get("json", False), columns=cols))


# ---------------------------------------------------------------------------
# Recursive builder: three explicit per-IdClass registrars (the per-IdClass
# registrar fallback promoted to primary, per the plan — keeps --help readable).
# ---------------------------------------------------------------------------
def _singular(name: str) -> str:
    """Resource (plural, kebab) -> a positional metavar: versions->VERSION,
    credentials->CREDENTIAL, memories->MEMORY, memory-versions->MEMORY_VERSION."""
    if name.endswith("ies"):
        base = name[:-3] + "y"
    elif name.endswith("s"):
        base = name[:-1]
    else:
        base = name
    return base.upper().replace("-", "_")


def _opt_flag(a: Resource) -> str:
    # ancestor Resource -> CLI option flag: session_id -> --session,
    # memory_store_id -> --memory-store, vault_id -> --vault.
    return "--" + a.parent_id_kw.removesuffix("_id").replace("_", "-")


_DATA_OPT_HELP = "JSON body, inline or @file.json"


def _register(sub: typer.Typer, path, verb: Verb) -> None:
    """Synthesize one Typer command for `verb` on sub-app `sub`. Dispatches on
    verb.id_class: PARENT_SCOPED puts the immediate parent positional (higher
    ancestors as options); CHILD/SELF put the own id positional (ancestors as
    options). Payload adds --data (JSON) or a FOLDER positional (skills)."""
    node = path[-1]
    ancestors = path[:-1]

    if verb.id_class is IdClass.PARENT_SCOPED:
        if not ancestors:                                          # flat root
            if verb.payload is Payload.JSON:
                @sub.command(verb.name)
                def _c(ctx: typer.Context,
                       data: str = typer.Option(None, "--data", help=_DATA_OPT_HELP)):
                    _run_node(ctx, path, verb, data=_read_data(data))
            else:                                                  # NONE (list)
                @sub.command(verb.name)
                def _c(ctx: typer.Context):
                    _run_node(ctx, path, verb)
            return

        immediate = ancestors[-1]
        higher = ancestors[:-1]
        pmeta = immediate.parent_id_kw.upper()
        if higher:                                                 # depth-3 (e.g. threads.events)
            if len(higher) != 1:
                raise RuntimeError(f"unsupported nesting depth for {node.name}")
            h = higher[0]
            hflag = _opt_flag(h)

            @sub.command(verb.name)
            def _c(ctx: typer.Context,
                   parent: str = typer.Argument(..., metavar=pmeta),
                   grandparent: str = typer.Option(..., hflag, help=f"{h.name} id")):
                _run_node(ctx, path, verb, ancestor_ids={
                    immediate.parent_id_kw: parent, h.parent_id_kw: grandparent})
            return

        if verb.payload is Payload.SKILL_FOLDER:                   # skills versions create
            @sub.command(verb.name)
            def _c(ctx: typer.Context,
                   parent: str = typer.Argument(..., metavar=pmeta),
                   folder: str = typer.Argument(..., metavar="FOLDER")):
                _run_node(ctx, path, verb,
                          ancestor_ids={immediate.parent_id_kw: parent}, folder=folder)
        elif verb.payload is Payload.JSON:                         # create / add
            @sub.command(verb.name)
            def _c(ctx: typer.Context,
                   parent: str = typer.Argument(..., metavar=pmeta),
                   data: str = typer.Option(None, "--data", help=_DATA_OPT_HELP)):
                _run_node(ctx, path, verb,
                          ancestor_ids={immediate.parent_id_kw: parent}, data=_read_data(data))
        else:                                                      # NONE (list / stats)
            @sub.command(verb.name)
            def _c(ctx: typer.Context,
                   parent: str = typer.Argument(..., metavar=pmeta)):
                _run_node(ctx, path, verb, ancestor_ids={immediate.parent_id_kw: parent})
        return

    if verb.id_class is IdClass.CHILD:
        imeta = _singular(node.name)
        if not ancestors:                                          # flat root child verb
            if verb.payload is Payload.JSON:
                @sub.command(verb.name)
                def _c(ctx: typer.Context,
                       ident: str = typer.Argument(..., metavar=imeta),
                       data: str = typer.Option(None, "--data", help=_DATA_OPT_HELP)):
                    _run_node(ctx, path, verb, ident=ident, data=_read_data(data))
            else:
                @sub.command(verb.name)
                def _c(ctx: typer.Context,
                       ident: str = typer.Argument(..., metavar=imeta)):
                    _run_node(ctx, path, verb, ident=ident)
            return

        if len(ancestors) != 1:
            raise RuntimeError(f"unsupported CHILD nesting depth for {node.name}")
        a = ancestors[0]
        aflag = _opt_flag(a)
        if verb.payload is Payload.JSON:                           # update
            @sub.command(verb.name)
            def _c(ctx: typer.Context,
                   ident: str = typer.Argument(..., metavar=imeta),
                   parent: str = typer.Option(..., aflag, help=f"{a.name} id"),
                   data: str = typer.Option(None, "--data", help=_DATA_OPT_HELP)):
                _run_node(ctx, path, verb, ident=ident,
                          ancestor_ids={a.parent_id_kw: parent}, data=_read_data(data))
        else:                                                      # get / delete / archive / redact / validate
            @sub.command(verb.name)
            def _c(ctx: typer.Context,
                   ident: str = typer.Argument(..., metavar=imeta),
                   parent: str = typer.Option(..., aflag, help=f"{a.name} id")):
                _run_node(ctx, path, verb, ident=ident,
                          ancestor_ids={a.parent_id_kw: parent})
        return

    if verb.id_class is IdClass.SELF:                              # depth-1 action verbs
        imeta = _singular(node.name)

        @sub.command(verb.name)
        def _c(ctx: typer.Context,
               ident: str = typer.Argument(..., metavar=imeta)):
            _run_node(ctx, path, verb, ident=ident)
        return


def _make_app(path) -> typer.Typer:
    node = path[-1]
    sub = typer.Typer(no_args_is_help=True, help=f"Manage {node.name}.")
    for verb in node.verbs:
        _register(sub, path, verb)
    for childres in node.children:
        sub.add_typer(_make_app(path + (childres,)), name=childres.name)
    return sub


# ---------------------------------------------------------------------------
# Preserved non-generic skills commands (Phase 2 bodies, kept verbatim).
# ---------------------------------------------------------------------------
def _run_raw(ctx, fn, *, verb: str, target: str) -> None:
    """client / safety / error boilerplate for commands that emit their own output
    (binary download, file extraction) instead of a rendered model object."""
    opts = ctx.obj or {}
    try:
        safety_check(verb, target, yes=opts.get("yes", False))
        settings = load_settings(profile=opts.get("profile"))
        fn(build_client(settings), opts)
    except Exception as exc:  # noqa: BLE001 - mapped to exit codes
        msg, code = format_error(exc)
        if opts.get("json", False):
            typer.echo(_json.dumps({"error": msg, "exit_code": code}), err=True)
        else:
            typer.echo(msg, err=True)
        raise typer.Exit(code)


def _attach_skill_alias(sub: typer.Typer, skills_root: Resource) -> None:
    """Preserve the shipped non-generic skills commands: `skills update` (alias of
    versions.create) + `skills show` + `skills download`. `update` routes through the
    generic dispatcher (identical to `skills versions create`); `show`/`download` keep
    their Phase 2 bodies verbatim (binary bundle download + Zip-Slip-guarded extract)."""
    versions_node = next(c for c in skills_root.children if c.name == "versions")
    create_verb = next(v for v in versions_node.verbs if v.name == "create")
    vpath = (skills_root, versions_node)

    @sub.command("update")
    def _update(ctx: typer.Context, skill_id: str, folder: str):
        """Publish a NEW VERSION of a skill from FOLDER (must contain SKILL.md)."""
        _run_node(ctx, vpath, create_verb,
                  ancestor_ids={skills_root.parent_id_kw: skill_id}, folder=folder)

    @sub.command("show")
    def _show(ctx: typer.Context, skill_id: str,
              version: str = typer.Option(None, "--version", help="Version id (default: latest).")):
        """Print a skill version's SKILL.md (downloads the bundle, reads it in memory)."""
        def go(client, opts):
            ver, data = skill_zip(client, skill_id, version)
            zf = zipfile.ZipFile(io.BytesIO(data))
            md = next((n for n in zf.namelist() if n.endswith("SKILL.md")), None)
            content = zf.read(md).decode() if md else ""
            if opts.get("json", False):
                typer.echo(_json.dumps({"skill_id": skill_id, "version": ver,
                                        "files": zf.namelist(), "skill_md": content}))
            else:
                typer.echo(content or "(no SKILL.md in the bundle)")
        _run_raw(ctx, go, verb="get", target=skill_id)

    @sub.command("download")
    def _download(ctx: typer.Context, skill_id: str,
                  out: str = typer.Option(..., "--out", help="Directory to extract the bundle into."),
                  version: str = typer.Option(None, "--version", help="Version id (default: latest).")):
        """Download a skill version's full bundle and extract it into --out."""
        def go(client, opts):
            ver, data = skill_zip(client, skill_id, version)
            dest = pathlib.Path(out).expanduser()
            dest.mkdir(parents=True, exist_ok=True)
            zf = zipfile.ZipFile(io.BytesIO(data))
            files = safe_extract(zf, dest)
            if opts.get("json", False):
                typer.echo(_json.dumps({"skill_id": skill_id, "version": ver,
                                        "out": str(dest), "files": files}))
            else:
                typer.echo(f"extracted {len(files)} file(s) to {dest}:")
                for n in files:
                    typer.echo(f"  {n}")
        _run_raw(ctx, go, verb="get", target=skill_id)


for _root in RESOURCES.values():
    _sub = _make_app((_root,))
    if _root.name == "skills":
        _attach_skill_alias(_sub, _root)
    app.add_typer(_sub, name=_root.name)


# ---------------------------------------------------------------------------
# Whole-workspace operations (export the control plane as a git-ready tree).
# ---------------------------------------------------------------------------
workspace_app = typer.Typer(no_args_is_help=True, help="Whole-workspace operations.")


@workspace_app.command("export")
def _workspace_export(
    ctx: typer.Context,
    out: str = typer.Argument(..., metavar="DIR", help="Directory to write the export into."),
    skill_bundles: bool = typer.Option(
        True, "--skill-bundles/--no-skill-bundles",
        help="Download + extract each skill's bundle (default: on)."),
    git: bool = typer.Option(
        False, "--git", help="After export, git init + add + commit the directory."),
    push: str = typer.Option(
        None, "--push", metavar="OWNER/REPO",
        help="Commit (implies --git) and push to a GitHub repo via gh (created PRIVATE)."),
    public: bool = typer.Option(
        False, "--public", help="With --push, create the repo PUBLIC instead of private."),
    message: str = typer.Option(
        None, "--message", "-m", help="Commit message for --git/--push."),
    if_changed: bool = typer.Option(
        False, "--if-changed",
        help="With --git/--push, skip the commit when only the export timestamp changed "
             "(no workspace change) — clean history for scheduled backups."),
):
    """Snapshot the workspace's config resources into a git-ready tree (secrets excluded).

    Writes agents (config + version history), skill bundles, and vault / memory-store /
    environment / deployment metadata as JSON under DIR. Vault credential SECRET VALUES
    are write-only and are never exported. Read-only against the workspace; safe to re-run.

    With --git it also commits the directory; with --push OWNER/REPO it pushes to GitHub
    via the gh CLI (creating the repo PRIVATE by default, --public to override). If the
    repo already EXISTS, DIR is first cloned from it so the export commits as a diff on
    top of the repo's current content (DIR must be empty or already that clone)."""
    from claude_platform import workspace as _ws  # lazy: avoids import cost on every CLI call

    opts = ctx.obj or {}
    repo_url = None
    committed = False
    _vcs = None
    if git or push:
        from claude_platform import vcs as _vcs  # lazy: only when publishing
    try:
        # Publishing to an EXISTING repo: base DIR on it (clone) so the export is a diff
        # on top of the repo's content, not a divergent root commit that can't push.
        if push and _vcs.github_repo_exists(push):
            _vcs.ensure_clone(push, out)
        settings = load_settings(profile=opts.get("profile"))
        client = build_client(settings)
        manifest = _ws.export_workspace(
            client, out, workspace_id=settings.workspace_id, region=settings.region,
            include_skill_bundles=skill_bundles)
        if _vcs is not None:
            msg = message or f"workspace snapshot {manifest['exported_at']}"
            # Stage only the export's own paths so a stray file in DIR is never committed.
            committed = _vcs.ensure_git(manifest["out"], msg,
                                        paths=[*_ws.EXPORT_TOPLEVEL, ".gitignore"],
                                        if_changed=if_changed)
            if push:
                repo_url = _vcs.push_github(manifest["out"], push, private=not public)
    except Exception as exc:  # noqa: BLE001 - mapped to exit codes
        emsg, code = format_error(exc)
        if opts.get("json", False):
            typer.echo(_json.dumps({"error": emsg, "exit_code": code}), err=True)
        else:
            typer.echo(emsg, err=True)
        raise typer.Exit(code)

    if opts.get("json", False):
        typer.echo(_json.dumps({**manifest, "committed": committed, "repo_url": repo_url},
                               indent=2, default=str))
    else:
        counts = manifest["counts"]
        typer.echo(f"Exported workspace to {manifest['out']}:")
        for key in ("agents", "skills", "vaults", "memory_stores",
                    "environments", "deployments"):
            typer.echo(f"  {key}: {counts.get(key, 0)}")
        if manifest["errors"]:
            typer.echo(f"  ({len(manifest['errors'])} section(s) skipped — see manifest.json)")
        if git or push:
            typer.echo("  committed" if committed else "  (git: nothing to commit)")
        if repo_url:
            typer.echo(f"  pushed -> {repo_url}")


app.add_typer(workspace_app, name="workspace")


def shell_namespace(profile: str | None = None) -> dict:
    settings = load_settings(profile=profile)
    return {"client": build_client(settings), "settings": settings}


@app.command()
def shell(ctx: typer.Context) -> None:
    """Open a Python REPL with a ready `client` (AnthropicAWS)."""
    import code

    opts = ctx.obj or {}
    ns = shell_namespace(profile=opts.get("profile"))
    banner = (f"claude-platform shell — `client` ready "
              f"(workspace {ns['settings'].workspace_id}, {ns['settings'].region})")
    code.interact(banner=banner, local=ns)
