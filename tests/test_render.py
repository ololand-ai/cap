import json
from claude_platform.render import render

def test_json_output_roundtrips():
    out = render([{"id": "a", "name": "x"}], as_json=True)
    assert json.loads(out) == [{"id": "a", "name": "x"}]

def test_json_output_single_object():
    out = render({"id": "a"}, as_json=True)
    assert json.loads(out) == {"id": "a"}

def test_table_includes_values_and_selected_columns():
    out = render(
        [{"id": "a1", "name": "Agent One", "secret": "hide"}],
        as_json=False,
        columns=["id", "name"],
    )
    assert "a1" in out and "Agent One" in out
    assert "secret" not in out

def test_table_handles_empty_list():
    out = render([], as_json=False, columns=["id"])
    assert isinstance(out, str)
