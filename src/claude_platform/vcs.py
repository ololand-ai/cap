"""Optional git / GitHub publishing for `cap workspace export`.

Shells out to `git` and the `gh` CLI (both expected on PATH). Subprocess calls use
list-form args (never `shell=True`), so a repo name or commit message cannot inject
shell commands. Private-by-default: a public GitHub repo is created only when the
caller explicitly opts in.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

# OWNER/REPO or REPO; each segment must NOT start with '-' (so an untrusted value like
# "--public" can't be parsed by gh as a flag) and is restricted to GitHub-legal chars.
_REPO_RE = re.compile(r"^[A-Za-z0-9._][A-Za-z0-9._-]*(/[A-Za-z0-9._][A-Za-z0-9._-]*)?$")


class VcsError(Exception):
    """A git/gh operation failed, or a required binary is missing."""


def _run(args: list[str], cwd: pathlib.Path) -> str:
    try:
        proc = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True)  # noqa: S603
    except FileNotFoundError as exc:  # binary missing entirely -> consistent VcsError
        raise VcsError(f"executable '{args[0]}' not found on PATH") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise VcsError(f"`{' '.join(args)}` failed: {detail}")
    return proc.stdout.strip()


def _ensure_identity(dest: pathlib.Path) -> None:
    # Set a local fallback ONLY for whichever of email/name is unconfigured — checked
    # independently so we never override the user's existing global identity. (If the
    # user has a global name but no global email, only the email gets a local fallback.)
    try:
        _run(["git", "config", "user.email"], dest)
    except VcsError:
        _run(["git", "config", "user.email", "cap@localhost"], dest)
    try:
        _run(["git", "config", "user.name"], dest)
    except VcsError:
        _run(["git", "config", "user.name", "cap (claude-platform)"], dest)


def _write_gitignore(dest: pathlib.Path) -> None:
    gi = dest / ".gitignore"
    if not gi.exists():
        gi.write_text(".DS_Store\n__pycache__/\n*.pyc\n")


def _only_timestamp_changed(dest: pathlib.Path) -> bool:
    """True if the staged diff for manifest.json touches ONLY the volatile `exported_at`
    field — i.e. the workspace content is unchanged, just the snapshot time moved."""
    diff = _run(["git", "diff", "--cached", "-U0", "--", "manifest.json"], dest)
    changed = [ln for ln in diff.splitlines()
               if ln[:1] in "+-" and not ln.startswith(("+++", "---"))]
    return bool(changed) and all('"exported_at":' in ln for ln in changed)


def ensure_git(dest, message: str, paths=None, if_changed: bool = False) -> bool:
    """`git init` (if needed) + add + commit. If `paths` is given, ONLY those relative
    paths are staged — scoping the commit to the export's own output so an unrelated file
    already sitting in the directory (e.g. a stray `.env` or project sources) is never
    committed. If `paths` is None, all changes are staged (`git add -A`). If `if_changed`
    is True, the commit is skipped when the only staged change is manifest.json's
    `exported_at` timestamp (so re-runs over an unchanged workspace don't add noise).
    Returns True if a commit was made, False if nothing was committed. Raises VcsError if
    git missing/fails."""
    if shutil.which("git") is None:
        raise VcsError("git not found on PATH")
    dest = pathlib.Path(dest)
    if not (dest / ".git").is_dir():
        _run(["git", "init", "-q"], dest)
    _ensure_identity(dest)
    _write_gitignore(dest)
    if paths is not None:
        # Stage a managed path if it exists OR is still tracked (so a resource that was
        # removed since the last snapshot is staged as a DELETION). `-A` records
        # add/modify/delete within each path; `git add -- <never-tracked & missing>` is
        # fatal, hence the exists-or-tracked filter.
        to_add = []
        for p in paths:
            if (dest / p).exists():
                to_add.append(p)
            else:
                try:
                    if _run(["git", "ls-files", "--", p], dest):
                        to_add.append(p)
                except VcsError:
                    pass
        if to_add:
            _run(["git", "add", "-A", "--", *to_add], dest)
    else:
        _run(["git", "add", "-A"], dest)
    # Decide on STAGED changes only — untracked strays must not trigger a commit.
    staged = _run(["git", "diff", "--cached", "--name-only"], dest).split()
    if not staged:
        return False
    if if_changed and staged == ["manifest.json"] and _only_timestamp_changed(dest):
        # Only the snapshot timestamp moved -> not a real change: unstage + restore it.
        _run(["git", "reset", "-q", "HEAD", "--", "manifest.json"], dest)
        _run(["git", "checkout", "-q", "--", "manifest.json"], dest)
        return False
    _run(["git", "commit", "-q", "-m", message], dest)
    return True


def github_repo_exists(repo: str) -> bool:
    """True if GitHub `repo` (OWNER/REPO or REPO) already exists and is visible to `gh`."""
    if not _REPO_RE.match(repo or ""):
        raise VcsError(f"invalid repo name {repo!r}")
    if shutil.which("gh") is None:
        raise VcsError("gh CLI not found on PATH (install: https://cli.github.com)")
    try:
        _run(["gh", "repo", "view", repo], pathlib.Path.home())
        return True
    except VcsError:
        return False


def _norm_repo(ref: str) -> str:
    """Normalize a git remote URL or OWNER/REPO ref to 'owner/repo' (lowercased) so the
    OWNER is compared, not just the trailing name. Handles https://host/o/r(.git) and
    git@host:o/r(.git); a bare 'repo' stays 'repo' (which therefore never matches an
    owner-qualified origin)."""
    s = ref.strip().removesuffix(".git")
    if "://" in s:                                        # scheme://host/owner/repo
        s = s.split("://", 1)[1]
        s = s.split("/", 1)[1] if "/" in s else ""        # drop host
    elif "@" in s and ":" in s.split("@", 1)[1]:          # git@host:owner/repo
        s = s.split(":", 1)[1]
    return s.strip("/").lower()


def ensure_clone(repo: str, dest) -> bool:
    """Make `dest` a working clone of GitHub `repo` so an export becomes a diff on top of
    the repo's current content (a fast-forward push, not a divergent-history rejection).
    Returns True if it cloned, False if `dest` was already a clone of `repo`. Raises if
    `dest` exists with a different origin, or is a non-empty non-clone directory."""
    # Resolve to an absolute path so the clone lands at exactly `dest` regardless of the
    # working dir (a relative `backups/ws` would otherwise double-nest under cwd).
    dest = pathlib.Path(dest).expanduser().resolve()
    if (dest / ".git").is_dir():
        try:
            url = _run(["git", "remote", "get-url", "origin"], dest)
        except VcsError:
            url = ""
        # Match the FULL owner/repo, not just the trailing name, so an existing clone of a
        # same-named repo owned by someone else is NOT treated as the right clone.
        if url and _norm_repo(url) == _norm_repo(repo):
            # Bring the existing clone up to date so the new commit fast-forwards (another
            # machine may have pushed the last scheduled snapshot).
            try:
                _run(["git", "pull", "--ff-only", "-q"], dest)
            except VcsError as exc:
                raise VcsError(f"{dest} is a clone of {repo} but couldn't fast-forward to "
                               f"origin: {exc}. Resolve it manually.") from exc
            return False                                  # already a clone of exactly `repo`
        raise VcsError(f"{dest} is already a git repo (origin={url or 'none'}); refusing "
                       f"to overwrite it with a clone of {repo}")
    if dest.exists() and any(dest.iterdir()):
        raise VcsError(f"{dest} is non-empty and not a clone of {repo}; use an empty or "
                       "new directory (or pre-clone the repo)")
    if shutil.which("gh") is None:
        raise VcsError("gh CLI not found on PATH (install: https://cli.github.com)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    _run(["gh", "repo", "clone", repo, str(dest)], dest.parent)
    return True


def push_github(dest, repo: str, *, private: bool = True) -> str:
    """Push `dest` to GitHub via `gh`. If an `origin` remote already exists, push to it;
    otherwise create the repo (private unless `private=False`) and push. Returns the
    remote URL. Raises VcsError if `repo` is malformed or gh is missing/fails."""
    if not _REPO_RE.match(repo or ""):
        raise VcsError(
            f"invalid repo name {repo!r}: expected OWNER/REPO or REPO using letters, "
            "digits, '.', '_', '-' (and not starting with '-')")
    dest = pathlib.Path(dest)
    if "origin" in _run(["git", "remote"], dest).split():
        _run(["git", "push", "-u", "origin", "HEAD"], dest)
        return _run(["git", "remote", "get-url", "origin"], dest)
    if shutil.which("gh") is None:
        raise VcsError("gh CLI not found on PATH (install: https://cli.github.com)")
    visibility = "--private" if private else "--public"
    _run(["gh", "repo", "create", repo, visibility,
          "--source", ".", "--push", "--remote", "origin"], dest)
    return _run(["git", "remote", "get-url", "origin"], dest)
