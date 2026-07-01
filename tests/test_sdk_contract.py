"""Guards EVERY registered CLI verb at EVERY depth against the real anthropic SDK.

Builds AnthropicAWS(skip_auth=True): resolves no AWS creds, makes NO network call —
only lets us introspect the resource objects. Recurses the resource tree and resolves
SDK methods with the SAME precedence the dispatcher uses (verb.sdk_method or
_SDK_METHOD.get(name) or name). This is the unit-time guard that would have caught the
original skills.versions invisibility, and now catches drift at any depth.
"""
import anthropic
import pytest

from claude_platform.cli import _SDK_METHOD
from claude_platform.resources import RESOURCES, Resource


@pytest.fixture(scope="module")
def offline_client():
    return anthropic.AnthropicAWS(skip_auth=True, aws_region="us-east-1", workspace_id="x")


def _walk(node: Resource, path):
    path = path + (node,)
    yield path
    for c in node.children:
        yield from _walk(c, path)


def _sdk_obj(client, path):
    obj = client.beta
    for r in path:
        obj = getattr(obj, r.attr, None)
        if obj is None:
            return None, r
    return obj, None


def test_every_registered_verb_maps_to_a_real_sdk_method(offline_client):
    missing = []
    for root in RESOURCES.values():
        for path in _walk(root, ()):
            sdk_obj, broke = _sdk_obj(offline_client, path)
            dotted = ".".join(r.name for r in path)
            attr_path = "beta." + ".".join(r.attr for r in path)
            assert sdk_obj is not None, f"{attr_path} missing for '{dotted}' (at {broke.attr})"
            for verb in path[-1].verbs:
                method = verb.sdk_method or _SDK_METHOD.get(verb.name, verb.name)
                if not hasattr(sdk_obj, method):
                    missing.append(f"{dotted}.{verb.name} -> {attr_path}.{method}")
    assert not missing, "registered verbs with no matching SDK method:\n" + "\n".join(missing)


# Data-plane EXCLUSION is a charter invariant, so assert it directly: the worker/turn
# verbs must never appear anywhere in the tree, and `environments.work` must never
# register `update` specifically. NOTE: `update` is excluded ONLY for environments.work
# (it is a legitimate verb on memories, user-profiles, sessions.resources,
# vaults.credentials), so do NOT forbid `update` globally.
DATA_PLANE_WORKER_VERBS = frozenset({"send", "stream", "poll", "ack", "heartbeat", "stop"})


def _all_verb_names():
    names = set()
    for root in RESOURCES.values():
        for path in _walk(root, ()):
            names.update(v.name for v in path[-1].verbs)
    return names


def _node_by_path(*segments):
    """Resolve a node by CLI path, or return None if not (yet) registered."""
    node = RESOURCES.get(segments[0])
    for seg in segments[1:]:
        if node is None:
            return None
        node = next((c for c in node.children if c.name == seg), None)
    return node


def test_data_plane_worker_verbs_globally_absent():
    # {send,stream,poll,ack,heartbeat,stop} are data plane -> never registered at any depth.
    registered = _all_verb_names()
    assert DATA_PLANE_WORKER_VERBS.isdisjoint(registered), (
        "data-plane worker/turn verbs leaked into the registry: "
        + ", ".join(sorted(DATA_PLANE_WORKER_VERBS & registered))
    )


def test_environments_work_does_not_register_update():
    # `update` is excluded for the worker loop specifically (it IS legit elsewhere).
    # The node only exists once Task 7 lands; guard so this passes at every increment.
    work = _node_by_path("environments", "work")
    if work is not None:
        assert "update" not in {v.name for v in work.verbs}
    # sanity: `update` remains a registered verb somewhere else in the tree.
    assert "update" in _all_verb_names()
