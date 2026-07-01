# claude-platform

A thin CLI over the Anthropic `AnthropicAWS` SDK to manage a Claude Platform on AWS
workspace (agents, sessions, …) from any directory. The official `ant` CLI cannot
reach the AWS variant (no SigV4, no `anthropic-workspace-id` header); the SDK can,
and this wraps it.

## Scope: control plane, not data plane

`cap` manages **resources** — CRUD over agents, sessions, environments, vaults,
memory-stores, skills, deployments, and files. That's the control plane. It does
**not** drive a running agent: no sending `user.message` events, no SSE streaming,
no custom-tool results, no defining outcomes. To actually run a session, provision
and inspect with `cap`, then interact with the SDK — drop into `cap shell` (a Python
REPL with a ready `client`) or use app code. This mirrors Anthropic's own split:
CLI for the control plane, SDK for the data plane.

The workspace's nested control-plane sub-resources are exposed too (Phase 3):
`vaults.credentials`, `memory-stores.memories`/`memory-versions`,
`sessions.resources`/`threads`/`threads.events`/`events`, `environments.work`, and
`agents.versions`, plus the `deployment-runs` and `user-profiles` flat resources and
`deployments` `pause`/`unpause`/`run`. See **Nested resources** below. Still
data-plane (not CLI): `sessions events send`, all `*.stream`, and the
`environments work` runtime loop. Separately,
**skill versioning** (`skills.versions`) — surfaced as `cap skills update` /
`cap skills versions`, since publishing a new version is how you update a skill
(skills are immutable per version; there is no in-place `skills.update`).
The metadata endpoints carry no skill *content*, so `cap skills show` /
`cap skills download` fetch the actual bundle (`skills.versions.download` returns a
zip) — `show` prints `SKILL.md`, `download` extracts the whole bundle to a folder.

## Install

    uv tool install --editable .

This puts `claude-platform` and `cap` on your PATH (~/.local/bin).

## Setup

    claude-platform init        # writes ~/.config/claude-platform/config.toml
    # edit it: set workspace_id + region. AWS creds come from your ~/.aws chain.

## Use

    cap agents list
    cap --json agents get agent_01...
    cap --yes agents archive agent_01...   # destructive verbs need --yes
    cap shell                              # Python REPL with a ready `client`

    # Skills — "update" publishes a new VERSION (the folder needs a SKILL.md, all files
    # nested under one top-level dir named for the skill). Agents attached at version
    # "latest" pick it up on their next session.
    cap skills list
    cap skills update skill_01... path/to/skill   # publish a new version
    cap skills versions list skill_01...          # see published versions
    cap skills show skill_01...                   # print the latest SKILL.md (content, not metadata)
    cap skills show skill_01... --version 17...    # a specific version's SKILL.md
    cap skills download skill_01... --out ./skill  # extract the whole bundle to a folder

## Nested resources (control plane)

`cap` exposes the workspace's nested control-plane sub-resources. Parent ids thread
through positionally for parent-scoped reads/creates and as `--<parent>` options for
child-targeted ops:

    cap agents versions list AGENT_ID
    cap vaults credentials list VAULT_ID
    cap vaults credentials get CRED_ID --vault VAULT_ID
    cap vaults credentials validate CRED_ID --vault VAULT_ID
    cap memory-stores memories create STORE_ID --data '{"content":"...","path":"notes/a"}'
    cap memory-stores memory-versions redact VER_ID --memory-store STORE_ID --yes
    cap sessions resources add SESSION_ID --data '{"file_id":"f_1","type":"file"}'
    cap sessions threads list SESSION_ID
    cap sessions threads events list THREAD_ID --session SESSION_ID   # two-deep
    cap sessions events list SESSION_ID
    cap environments work stats ENV_ID
    cap skills versions get VERSION --skill SKILL_ID
    cap deployments pause DEPLOY_ID
    cap deployments run DEPLOY_ID --yes                # billable -> gated
    cap deployment-runs list --data '{"deployment_id":"dep_1"}'
    cap user-profiles create-enrollment-url PROFILE_ID

Still **data plane** (use `cap shell` / the SDK): `sessions events send`,
all `*.stream`, and `environments work {poll,ack,heartbeat,stop,update}` — these
drive a running agent / the worker loop and are intentionally not CLI commands.

## Export the workspace (workspace-as-code)

Snapshot the workspace's control plane into a git-ready JSON tree:

    cap workspace export ./workspace-snapshot

Writes, under the target dir: `agents/<id>.json` (full config + version history),
`skills/<id>/` (metadata + the extracted bundle), `vaults/<id>.json`,
`memory-stores/`, `environments/`, `deployments/`, and a top-level `manifest.json`
(workspace id, region, timestamp, per-resource counts, and any skipped sections).
Read-only and safe to re-run. Pass `--no-skill-bundles` to skip downloading bundles.
Export refuses to overwrite a **non-empty** directory that isn't a prior cap export or a
git repo, so it won't clobber a real `agents/` / `skills/` project — use an empty or
dedicated directory.

Publish it in one step (commit, and optionally push to GitHub via the `gh` CLI):

    cap workspace export ./snapshot --git                 # git init + commit the tree
    cap workspace export ./snapshot --push owner/repo     # commit + push (creates repo)
    cap workspace export ./snapshot --push owner/repo --public      # ... as a public repo
    cap workspace export ./snapshot --push owner/repo --if-changed  # skip no-op commits

`--push` pushes to GitHub via `gh`, **private by default** (use `--public` to override).
If the repo does **not** exist it is created; if it **already exists**, DIR is first
cloned from it so the export commits as a diff on top of the repo's current content (DIR
must be empty or already that clone). Only the export's own paths are committed — a stray
file in DIR is never staged. Each export reflects the *current* workspace, so a resource
that disappeared (e.g. an archived agent) shows up as a deletion. `--if-changed` skips the
commit when only the export timestamp moved (no real workspace change), so scheduled
backups don't pile up empty commits. `-m/--message` sets the commit message. `--git` /
`--push` need `git` (and, for `--push`, `gh`) on your PATH.

**Secrets aren't exported.** The load-bearing guarantee is the API contract: vault
credential secret *values* are write-only and are never returned on read, so they can't
reach the export. As defence-in-depth, every record is run through redaction — masking
sensitive-keyed fields and scrubbing known token shapes / URL-embedded credentials out
of free-form values (system prompts, MCP URLs, metadata). That value scrub is
best-effort, not a guarantee against an arbitrary secret you pasted into a prompt, so
keep the snapshot private. Re-inject secrets from your own secret manager when
re-creating. Resource ids are per-account, so re-creating into another workspace mints
new ids.

## Manual smoke test (hits real AWS)

With `~/.aws` SigV4 creds and a configured workspace:

    cap agents list

Expect your workspace's agents. This is the only test that touches AWS; the
automated suite mocks the SDK.

## Develop

    uv run pytest
