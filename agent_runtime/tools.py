from __future__ import annotations

import ast
import operator
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from .models import Session, TodoItem, ToolResult


@dataclass
class ToolContext:
    session: Session


class Tool(ABC):
    name: str
    description: str
    parameters: dict[str, Any]

    @abstractmethod
    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        raise NotImplementedError

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class ToolRegistry:
    def __init__(self, max_result_chars: int = 4000) -> None:
        self._tools: dict[str, Tool] = {}
        self.max_result_chars = max_result_chars

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具重复注册: {tool.name}")
        self._tools[tool.name] = tool

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.schema() for tool in self._tools.values()]

    def execute(
        self, name: str, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(ok=False, error=f"未知工具: {name}")
        error = validate_arguments(tool.parameters, arguments)
        if error:
            return ToolResult(ok=False, error=error)
        try:
            result = tool.execute(arguments, context)
        except Exception as exc:  # Tool boundary: one broken tool must not stop the loop.
            return ToolResult(ok=False, error=f"工具执行失败: {type(exc).__name__}: {exc}")
        rendered = str(result.data)
        if len(rendered) > self.max_result_chars:
            result.data = rendered[: self.max_result_chars] + "…[truncated]"
        return result


def validate_arguments(schema: dict[str, Any], value: Any) -> str | None:
    if not isinstance(value, dict):
        return "工具参数必须是 JSON object"
    required = schema.get("required", [])
    for name in required:
        if name not in value:
            return f"缺少必填参数: {name}"
    properties = schema.get("properties", {})
    if schema.get("additionalProperties") is False:
        unknown = set(value) - set(properties)
        if unknown:
            return f"包含未知参数: {sorted(unknown)[0]}"
    type_map = {"string": str, "integer": int, "number": (int, float), "boolean": bool}
    for name, item in value.items():
        spec = properties.get(name)
        if not spec:
            continue
        expected = type_map.get(spec.get("type"))
        if expected and (not isinstance(item, expected) or isinstance(item, bool) and spec.get("type") != "boolean"):
            return f"参数 {name} 类型错误，应为 {spec['type']}"
        if "enum" in spec and item not in spec["enum"]:
            return f"参数 {name} 必须是 {spec['enum']} 之一"
    return None


class CalculatorTool(Tool):
    name = "calculator"
    description = "安全计算基础算术表达式，支持 + - * / // % ** 和括号。"
    parameters = {
        "type": "object",
        "properties": {"expression": {"type": "string", "description": "算术表达式"}},
        "required": ["expression"],
        "additionalProperties": False,
    }
    _binary = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }
    _unary = {ast.UAdd: operator.pos, ast.USub: operator.neg}

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        expression = arguments["expression"]
        if len(expression) > 200:
            return ToolResult(ok=False, error="表达式过长")
        try:
            tree = ast.parse(expression, mode="eval")
            value = self._evaluate(tree.body, depth=0)
        except (SyntaxError, TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
            return ToolResult(ok=False, error=f"无法计算: {exc}")
        return ToolResult(ok=True, data={"expression": expression, "result": value})

    def _evaluate(self, node: ast.AST, depth: int) -> int | float:
        if depth > 20:
            raise ValueError("表达式嵌套过深")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            if abs(node.value) > 10**100:
                raise ValueError("数值过大")
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in self._binary:
            left = self._evaluate(node.left, depth + 1)
            right = self._evaluate(node.right, depth + 1)
            if isinstance(node.op, ast.Pow) and abs(right) > 12:
                raise ValueError("指数过大")
            return self._binary[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in self._unary:
            return self._unary[type(node.op)](self._evaluate(node.operand, depth + 1))
        raise ValueError("表达式包含不允许的语法")


class SearchTool(Tool):
    name = "search"
    description = "在内置示例知识库中搜索资料；这是可离线测试的 mock 搜索。"
    parameters = {
        "type": "object",
        "properties": {"query": {"type": "string", "description": "搜索关键词"}},
        "required": ["query"],
        "additionalProperties": False,
    }
    _documents = [
        {"title": "Agent Runtime", "text": "Agent Runtime 负责循环、工具执行、状态与上下文管理。"},
        {"title": "Context 压缩", "text": "保留最近消息，并把较早对话压缩成包含目标、事实和待办的摘要。"},
        {"title": "Session 隔离", "text": "每个会话使用独立标识与持久化状态，避免窗口之间相互污染。"},
    ]

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        query = arguments["query"].strip().lower()
        if not query:
            return ToolResult(ok=False, error="query 不能为空")
        terms = [term for term in query.split() if term]
        scored = []
        for document in self._documents:
            text = f"{document['title']} {document['text']}".lower()
            score = sum(term in text for term in terms)
            if score:
                scored.append((score, document))
        results = [item for _, item in sorted(scored, key=lambda row: -row[0])[:3]]
        return ToolResult(ok=True, data={"mock": True, "query": query, "results": results})


class WeatherTool(Tool):
    name = "weather"
    description = "查询内置城市的示例天气；返回数据明确标记为 mock。"
    parameters = {
        "type": "object",
        "properties": {"city": {"type": "string", "description": "城市名，如北京"}},
        "required": ["city"],
        "additionalProperties": False,
    }
    _weather = {
        "北京": {"condition": "晴", "temperature_c": 28},
        "上海": {"condition": "多云", "temperature_c": 30},
        "深圳": {"condition": "阵雨", "temperature_c": 31},
        "杭州": {"condition": "多云", "temperature_c": 29},
    }

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        city = arguments["city"].strip()
        value = self._weather.get(city)
        if value is None:
            return ToolResult(ok=False, error=f"mock 数据中没有城市: {city}")
        return ToolResult(ok=True, data={"mock": True, "city": city, **value})


class TodoTool(Tool):
    name = "todo"
    description = "管理当前 Session 的待办，支持 add、list、complete。"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["add", "list", "complete"]},
            "text": {"type": "string", "description": "add 时的待办内容"},
            "id": {"type": "integer", "description": "complete 时的待办编号"},
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def execute(self, arguments: dict[str, Any], context: ToolContext) -> ToolResult:
        action = arguments["action"]
        todos = context.session.todos
        if action == "add":
            text = str(arguments.get("text", "")).strip()
            if not text:
                return ToolResult(ok=False, error="add 操作需要非空 text")
            next_id = max((item.id for item in todos), default=0) + 1
            item = TodoItem(id=next_id, text=text)
            todos.append(item)
            return ToolResult(ok=True, data=item.to_dict())
        if action == "complete":
            todo_id = arguments.get("id")
            if not isinstance(todo_id, int) or isinstance(todo_id, bool):
                return ToolResult(ok=False, error="complete 操作需要整数 id")
            for item in todos:
                if item.id == todo_id:
                    item.done = True
                    return ToolResult(ok=True, data=item.to_dict())
            return ToolResult(ok=False, error=f"待办不存在: {todo_id}")
        return ToolResult(ok=True, data=[item.to_dict() for item in todos])


def default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for tool in (CalculatorTool(), SearchTool(), WeatherTool(), TodoTool()):
        registry.register(tool)
    return registry
