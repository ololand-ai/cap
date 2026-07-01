import types
from claude_platform.resources import (
    RESOURCES, accessor, Resource, IdClass, Payload, GET, LIST,
)


def test_agents_and_sessions_registered():
    assert "agents" in RESOURCES and "sessions" in RESOURCES
    assert RESOURCES["agents"].attr == "agents"
    assert any(v.name == "list" for v in RESOURCES["agents"].verbs)


def test_accessor_chains_down_the_tree():
    # Exercise the accessor's getattr-chaining with synthetic nodes so it holds at
    # every increment (the real sessions.threads.events nesting lands in Task 6).
    leaf = object()
    threads = types.SimpleNamespace(events=leaf)
    sessions = types.SimpleNamespace(threads=threads)
    client = types.SimpleNamespace(beta=types.SimpleNamespace(sessions=sessions))
    s = Resource("sessions", "sessions", (), ())
    th = Resource("threads", "threads", (), ())
    ev = Resource("events", "events", (), ())
    assert accessor(client, (s, th, ev)) is leaf


def test_flat_accessor_one_level():
    sentinel = object()
    client = types.SimpleNamespace(beta=types.SimpleNamespace(agents=sentinel))
    assert accessor(client, (RESOURCES["agents"],)) is sentinel


def test_resource_is_frozen_and_has_tree_fields():
    r = Resource(name="x", attr="x", verbs=(LIST,), columns=("id",))
    assert r.name == "x" and r.children == () and r.parent_id_kw is None


def test_verb_is_a_value_object():
    assert GET.name == "get" and GET.sdk_method == "retrieve"
    assert GET.id_class is IdClass.CHILD and GET.payload is Payload.NONE


def test_all_flat_resources_registered_with_correct_attr():
    expected = {
        "agents": "agents", "sessions": "sessions", "environments": "environments",
        "vaults": "vaults", "memory-stores": "memory_stores", "skills": "skills",
        "deployments": "deployments", "files": "files",
    }
    for name, attr in expected.items():
        assert name in RESOURCES and RESOURCES[name].attr == attr


def test_files_get_override_migrated_to_verb_sdk_method():
    files = RESOURCES["files"]
    get = next(v for v in files.verbs if v.name == "get")
    assert get.sdk_method == "retrieve_metadata"


def test_skills_has_versions_child_with_shipped_verbs():
    skills = RESOURCES["skills"]
    versions = next(c for c in skills.children if c.name == "versions")
    names = {v.name for v in versions.verbs}
    assert {"create", "list"} <= names           # shipped surface preserved
    assert versions.parent_id_kw is None          # leaf: parent_id_kw unused (no children)
