from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class IdClass(Enum):
    PARENT_SCOPED = "parent_scoped"  # list/create/add/stats: NO own ident; IMMEDIATE parent id is
                                     #   leading positional, all higher ancestors keyword-only.
    CHILD = "child"                  # get/update/delete/archive/redact/validate: own ident leading
                                     #   positional; ALL ancestors keyword-only.
    SELF = "self"                    # depth-1 action verbs (pause/unpause/run/create-enrollment-url):
                                     #   own ident positional, no ancestors.


class Payload(Enum):
    NONE = "none"            # ident/parent-only (get/delete/archive/list/redact/stats/pause/unpause)
    JSON = "json"            # --data JSON merged into kwargs (create/update/add/user_profiles.create)
    SKILL_FOLDER = "skill"   # FOLDER positional -> _bundle_skill(folder) -> files=[...]
    URL = "url"              # response holds a URL field -> render it (create-enrollment-url)


@dataclass(frozen=True)
class Verb:
    name: str                       # CLI subcommand: get/list/create/redact/validate/pause/...
    id_class: IdClass
    payload: Payload = Payload.NONE
    sdk_method: str | None = None   # override CLI-verb -> SDK-method; else _SDK_METHOD then name
    destructive: bool = False       # routes through safety_check (delete/archive AND redact/run)
    columns: tuple[str, ...] | None = None  # per-verb table columns when the response model
                                            # diverges from the node's (e.g. work stats); None
                                            # falls back to the node's columns.


@dataclass(frozen=True)
class Resource:
    name: str                       # CLI segment (kebab ok): "memory-stores", "credentials", "events"
    attr: str                       # SDK attribute: "memory_stores", "credentials", "events"
    verbs: tuple[Verb, ...]
    columns: tuple[str, ...]
    parent_id_kw: str | None = None  # SDK kw name for THIS node's id when used as a parent
    children: tuple["Resource", ...] = ()


# ---- verb factories (keep the registry terse, mirror the old _AGENTS/_FULL constants) ----
def child(name, payload=Payload.NONE, sdk_method=None, destructive=False, columns=None):
    return Verb(name, IdClass.CHILD, payload, sdk_method, destructive, columns)


def scoped(name, payload=Payload.NONE, sdk_method=None, destructive=False, columns=None):
    return Verb(name, IdClass.PARENT_SCOPED, payload, sdk_method, destructive, columns)


def selfv(name, payload=Payload.NONE, sdk_method=None, destructive=False, columns=None):
    return Verb(name, IdClass.SELF, payload, sdk_method, destructive, columns)


GET = child("get", sdk_method="retrieve")
UPDATE = child("update", Payload.JSON)
DELETE = child("delete", destructive=True)
ARCH = child("archive", destructive=True)
LIST = scoped("list")
CREATE = scoped("create", Payload.JSON)

_AGENTS = (LIST, GET, CREATE, UPDATE, ARCH)
_FULL = (LIST, GET, CREATE, UPDATE, DELETE, ARCH)


RESOURCES: dict[str, Resource] = {
    "agents": Resource("agents", "agents", _AGENTS, ("id", "name", "created_at"),
                       parent_id_kw="agent_id",
                       children=(
                           # leaf: parent_id_kw unused (no children); dispatcher reads ancestors' kw
                           Resource("versions", "versions", (scoped("list"),),
                                    ("id", "created_at"), parent_id_kw=None),
                       )),
    "sessions": Resource(
        "sessions", "sessions", (LIST, GET, CREATE, DELETE),
        ("id", "status", "created_at"), parent_id_kw="session_id",
        children=(
            Resource("resources", "resources",
                     (scoped("add", Payload.JSON), LIST, GET, UPDATE, DELETE),
                     ("id", "type", "mount_path"), parent_id_kw="resource_id"),
            Resource("threads", "threads",
                     (LIST, GET, child("archive", destructive=True)),
                     ("id", "created_at"), parent_id_kw="thread_id",
                     children=(
                         # leaf: parent_id_kw unused (no children); dispatcher reads ancestors' kw
                         Resource("events", "events", (scoped("list"),),
                                  ("id", "type", "created_at"), parent_id_kw=None),
                     )),
            # leaf: parent_id_kw unused (no children); dispatcher reads ancestors' kw
            Resource("events", "events", (scoped("list"),),
                     ("id", "type", "created_at"), parent_id_kw=None),
        )),
    "environments": Resource(
        "environments", "environments", _FULL,
        ("id", "name", "type", "created_at"), parent_id_kw="environment_id",
        children=(
            # work list/get -> BetaSelfHostedWork (id/state/created_at); stats ->
            # BetaSelfHostedWorkQueueStats, a different shape, so it carries its own columns.
            Resource("work", "work",
                     (LIST, GET,
                      scoped("stats",
                             columns=("type", "depth", "pending", "workers_polling",
                                      "oldest_queued_at"))),
                     ("id", "state", "created_at"), parent_id_kw="work_id"),
        )),
    "vaults": Resource(
        "vaults", "vaults", _FULL, ("id", "display_name", "created_at"),
        parent_id_kw="vault_id",
        children=(
            Resource("credentials", "credentials",
                     (LIST, CREATE, GET, UPDATE, DELETE, ARCH,
                      child("validate", sdk_method="mcp_oauth_validate")),
                     ("id", "display_name", "created_at"), parent_id_kw="credential_id"),
        )),
    "memory-stores": Resource(
        "memory-stores", "memory_stores", _FULL, ("id", "name", "created_at"),
        parent_id_kw="memory_store_id",
        children=(
            Resource("memories", "memories", (LIST, CREATE, GET, UPDATE, DELETE),
                     ("id", "path", "created_at"), parent_id_kw="memory_id"),
            Resource("memory-versions", "memory_versions",
                     (LIST, GET, child("redact", destructive=True)),
                     ("id", "created_at"), parent_id_kw="memory_version_id"),
        )),
    "skills": Resource(
        "skills", "skills", (LIST, GET, CREATE, DELETE),
        ("id", "display_title", "created_at"), parent_id_kw="skill_id",
        children=(
            # create(folder) + list shipped in Phase 2; get/delete added in Task 9.
            # leaf: parent_id_kw unused (no children); the dispatcher reads ancestors' kw
            Resource("versions", "versions",
                     (scoped("create", Payload.SKILL_FOLDER), scoped("list"),
                      child("get", sdk_method="retrieve"),
                      child("delete", destructive=True)),
                     ("version", "created_at"), parent_id_kw=None),
        )),
    "deployments": Resource(
        "deployments", "deployments",
        (LIST, GET, CREATE, UPDATE, ARCH,
         selfv("pause"), selfv("unpause"), selfv("run", destructive=True)),
        ("id", "created_at"), parent_id_kw="deployment_id"),
    # `list` opts into Payload.JSON so `--data` server-side filters are synthesized and
    # merged into kwargs; standard LIST is Payload.NONE (no --data), so vaults/memory-stores
    # /etc. list verbs are unaffected. Flat root (no ancestors) -> list(**filters), no positional.
    "deployment-runs": Resource("deployment-runs", "deployment_runs",
                                (scoped("list", Payload.JSON), GET),
                                ("id", "status", "created_at")),
    "user-profiles": Resource(
        "user-profiles", "user_profiles",
        (LIST, GET, CREATE, UPDATE,
         selfv("create-enrollment-url", Payload.URL, sdk_method="create_enrollment_url")),
        ("id", "name", "relationship")),
    "files": Resource("files", "files",
                      (LIST, child("get", sdk_method="retrieve_metadata"), DELETE),
                      ("id", "created_at"), parent_id_kw="file_id"),
}


def accessor(client: Any, path: tuple[Resource, ...]) -> Any:
    """Chain getattr down the tree: beta.sessions.threads.events for path
    (sessions, threads, events). One-element path = a flat root (beta.<attr>)."""
    obj = client.beta
    for r in path:
        obj = getattr(obj, r.attr)
    return obj
