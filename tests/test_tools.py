if __name__ == "__main__":
    import _bootstrap

from agent_runtime.models import Session, ToolResult
from agent_runtime.tools import TOOLS, ToolContext, ToolRegistry, default_registry, run_calculator, run_todo

import pytest


def broken_tool(*, context):
    raise RuntimeError("expected failure")


def long_output_tool(*, context):
    return ToolResult(ok=True, data="x" * 100)


def schema(name):
    return {"name": name, "description": "test",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}


def test_calculator_is_safe():
    registry = ToolRegistry()
    registry.register(TOOLS[0], run_calculator)
    context = ToolContext(Session(id="s1"))
    assert registry.execute("calculator", {"expression": "(2 + 3) * 4"}, context).data["result"] == 20
    assert not registry.execute("calculator", {"expression": "__import__('os')"}, context).ok


def test_tool_schema_validation_and_unknown_tool():
    registry = ToolRegistry()
    registry.register(TOOLS[0], run_calculator)
    context = ToolContext(Session(id="s1"))
    assert not registry.execute("calculator", {}, context).ok
    assert not registry.execute("missing", {}, context).ok


def test_duplicate_registration():
    registry = ToolRegistry()
    registry.register(TOOLS[0], run_calculator)
    try:
        registry.register(TOOLS[0], run_calculator)
        assert False, "duplicate registration should fail"
    except ValueError:
        pass


def test_todo_belongs_to_session():
    first, second = Session(id="first"), Session(id="second")
    run_todo("add", text="写周报", context=ToolContext(first))
    assert len(first.todos) == 1
    assert second.todos == []


def test_tool_exception_is_returned_to_agent():
    registry = ToolRegistry()
    registry.register(schema("broken"), broken_tool)
    result = registry.execute("broken", {}, ToolContext(Session(id="s1")))
    assert not result.ok
    assert "expected failure" in result.error


def test_long_tool_output_is_truncated():
    registry = ToolRegistry(max_result_chars=12)
    registry.register(schema("long_output"), long_output_tool)
    result = registry.execute("long_output", {}, ToolContext(Session(id="s1")))
    assert result.ok
    assert result.data.endswith("[truncated]")
    assert len(result.data) < 100


@pytest.mark.parametrize("expression", ["1/0", "(-1)**0.5", "1e309", "(10**12)**12", "True+1"])
def test_calculator_rejects_invalid_or_unbounded_results(expression):
    result = default_registry().execute("calculator", {"expression": expression}, ToolContext(Session(id="s")))
    assert not result.ok


def test_schema_validation_prevents_invalid_todo_mutation():
    session = Session(id="s")
    registry = default_registry()
    for args in ({"action": "delete"}, {"action": "add", "text": 5},
                 {"action": "complete", "id": True}, {"action": "list", "extra": 1}):
        assert not registry.execute("todo", args, ToolContext(session)).ok
    assert session.todos == []


if __name__ == "__main__":
    raise SystemExit(_bootstrap.run(__file__))
