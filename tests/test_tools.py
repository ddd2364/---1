if __name__ == "__main__":
    import _bootstrap

from agent_runtime.models import Session, ToolResult
from agent_runtime.tools import CalculatorTool, TodoTool, Tool, ToolContext, ToolRegistry


class BrokenTool(Tool):
    name = "broken"
    description = "用于验证异常边界"
    parameters = {"type": "object", "properties": {}, "additionalProperties": False}

    def execute(self, arguments, context):
        raise RuntimeError("expected failure")


class LongOutputTool(Tool):
    name = "long_output"
    description = "用于验证输出裁剪"
    parameters = {"type": "object", "properties": {}, "additionalProperties": False}

    def execute(self, arguments, context):
        return ToolResult(ok=True, data="x" * 100)


def test_calculator_is_safe():
    registry = ToolRegistry()
    registry.register(CalculatorTool())
    context = ToolContext(Session(id="s1"))
    assert registry.execute("calculator", {"expression": "(2 + 3) * 4"}, context).data["result"] == 20
    assert not registry.execute("calculator", {"expression": "__import__('os')"}, context).ok


def test_tool_schema_validation_and_unknown_tool():
    registry = ToolRegistry()
    registry.register(CalculatorTool())
    context = ToolContext(Session(id="s1"))
    assert not registry.execute("calculator", {}, context).ok
    assert not registry.execute("missing", {}, context).ok


def test_duplicate_registration():
    registry = ToolRegistry()
    registry.register(CalculatorTool())
    try:
        registry.register(CalculatorTool())
        assert False, "duplicate registration should fail"
    except ValueError:
        pass


def test_todo_belongs_to_session():
    tool = TodoTool()
    first, second = Session(id="first"), Session(id="second")
    tool.execute({"action": "add", "text": "写周报"}, ToolContext(first))
    assert len(first.todos) == 1
    assert second.todos == []


def test_tool_exception_is_returned_to_agent():
    registry = ToolRegistry()
    registry.register(BrokenTool())
    result = registry.execute("broken", {}, ToolContext(Session(id="s1")))
    assert not result.ok
    assert "expected failure" in result.error


def test_long_tool_output_is_truncated():
    registry = ToolRegistry(max_result_chars=12)
    registry.register(LongOutputTool())
    result = registry.execute("long_output", {}, ToolContext(Session(id="s1")))
    assert result.ok
    assert result.data.endswith("[truncated]")
    assert len(result.data) < 100


if __name__ == "__main__":
    raise SystemExit(_bootstrap.run(__file__))
