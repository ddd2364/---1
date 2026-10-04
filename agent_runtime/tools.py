# 模块职责：按照参考 s02 的“Schema + 分发字典 + 普通函数”组织工具。
# 模型读取 Schema 来选择工具；注册中心校验参数后，才调用对应的 Python 函数。
from __future__ import annotations

import ast
import json
import math
import operator
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable

from .models import Session, TodoItem, ToolResult


@dataclass
class ToolContext:
    """向工具提供本次执行所需的受控运行时状态。"""

    # 工具所操作的当前会话由 Runtime 传入，不从全局变量中寻找会话。
    session: Session


# 和 s02 一样：Schema 告诉模型怎么调用，handler 负责真正执行。
ToolHandler = Callable[..., ToolResult]


class ToolRegistry:
    """负责工具注册、参数校验、异常隔离和结果大小控制。"""

    def __init__(self, max_result_chars: int = 4000) -> None:
        # tools 存说明，handlers 存函数；两份字典都以工具名称为键。
        self.tools: dict[str, dict[str, Any]] = {}
        self.handlers: dict[str, ToolHandler] = {}
        if max_result_chars < 1:
            raise ValueError("max_result_chars 必须大于 0")
        self.max_result_chars = max_result_chars

    def register(self, schema: dict[str, Any], handler: ToolHandler) -> None:
        name = schema["name"]
        if name in self.tools:
            raise ValueError(f"工具重复注册: {name}")
        # 复制嵌套 Schema，避免调用方后续修改原字典时连带修改注册结果。
        self.tools[name] = deepcopy(schema)
        self.handlers[name] = handler

    def schemas(self) -> list[dict[str, Any]]:
        # 只向上下文模块提供工具说明；Python 函数本身不能放进 JSON 请求。
        return deepcopy(list(self.tools.values()))

    def execute(
        self, name: str, arguments: dict[str, Any], context: ToolContext
    ) -> ToolResult:
        handler = self.handlers.get(name)
        if handler is None:
            return ToolResult(ok=False, error=f"未知工具: {name}")
        error = validate_arguments(self.tools[name]["parameters"], arguments)
        if error:
            return ToolResult(ok=False, error=error)
        # 工具是扩展边界：单个工具抛错应转换为结果，而不是终止整个 Agent 循环。
        try:
            # **arguments 展开模型参数，如 {"city": "北京"} 变成 city="北京"。
            # context 由程序提供，不属于模型可填写的工具参数。
            result = handler(context=context, **arguments)
            if not isinstance(result, ToolResult):
                raise TypeError("handler 必须返回 ToolResult")
            # 拒绝 NaN/Infinity，并检查结果能否序列化，避免写回上下文时出错。
            rendered = json.dumps(result.data, ensure_ascii=False, allow_nan=False)
        except Exception as exc:
            return ToolResult(ok=False, error=f"工具执行失败: {type(exc).__name__}: {exc}"[:self.max_result_chars])
        # 控制写回模型上下文的体积，防止超大工具结果挤占全部字符预算。
        if len(rendered) > self.max_result_chars:
            result.data = rendered[: self.max_result_chars] + "…[truncated]"
        if result.error:
            result.error = result.error[:self.max_result_chars]
        return result


def validate_arguments(schema: dict[str, Any], value: Any) -> str | None:
    """实现运行时所需的 JSON Schema 子集校验。"""

    if not isinstance(value, dict):
        return "工具参数必须是 JSON object"
    required = schema.get("required", [])
    # 校验分三步：必填字段是否存在、是否包含额外字段、各字段类型和枚举是否合法。
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
        # Python 的 bool 是 int 子类，需要显式排除，避免把 true 当作整数参数。
        if expected and (not isinstance(item, expected) or isinstance(item, bool) and spec.get("type") != "boolean"):
            return f"参数 {name} 类型错误，应为 {spec['type']}"
        if "enum" in spec and item not in spec["enum"]:
            return f"参数 {name} 必须是 {spec['enum']} 之一"
    return None


# ── 工具定义：名称、描述、参数 Schema ──

TOOLS = [
    # name 用于分发，description 帮助模型选择，parameters 描述参数的形状和约束。
    {"name": "calculator", "description": "安全计算基础算术表达式，支持 + - * / // % ** 和括号。",
     "parameters": {"type": "object",
                    "properties": {"expression": {"type": "string", "description": "算术表达式"}},
                    "required": ["expression"], "additionalProperties": False}},
    {"name": "search", "description": "在内置示例知识库中搜索资料；这是可离线测试的 mock 搜索。",
     "parameters": {"type": "object",
                    "properties": {"query": {"type": "string", "description": "搜索关键词"}},
                    "required": ["query"], "additionalProperties": False}},
    {"name": "weather", "description": "查询内置城市的示例天气；返回数据明确标记为 mock。",
     "parameters": {"type": "object",
                    "properties": {"city": {"type": "string", "description": "城市名，如北京"}},
                    "required": ["city"], "additionalProperties": False}},
    {"name": "todo", "description": "管理当前 Session 的待办，支持 add、list、complete。",
     "parameters": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["add", "list", "complete"]},
         "text": {"type": "string", "description": "add 时的待办内容"},
         "id": {"type": "integer", "description": "complete 时的待办编号"},
     }, "required": ["action"], "additionalProperties": False}},
]

# ── 工具实现 ──

BINARY = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod, ast.Pow: operator.pow,
}

# AST 运算符节点到函数的白名单；只解释这些节点，不执行任意 Python 源码。
UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}

# 搜索和天气使用内置演示数据，不会发起真实联网查询。
DOCUMENTS = [
    {"title": "Agent Runtime", "text": "Agent Runtime 负责循环、工具执行、状态与上下文管理。"},
    {"title": "Context 压缩", "text": "保留最近消息，并把较早对话压缩成包含目标、事实和待办的摘要。"},
    {"title": "Session 隔离", "text": "每个会话使用独立标识与持久化状态，避免窗口之间相互污染。"},
]

WEATHER = {
    "北京": {"condition": "晴", "temperature_c": 28},
    "上海": {"condition": "多云", "temperature_c": 30},
    "深圳": {"condition": "阵雨", "temperature_c": 31},
    "杭州": {"condition": "多云", "temperature_c": 29},
}


def evaluate(node: ast.AST, depth: int = 0) -> int | float:
    """AST 白名单求值；每个中间值也检查，避免幂运算逐层放大。"""
    if depth > 20:
        raise ValueError("表达式嵌套过深")
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        value = node.value
    elif isinstance(node, ast.BinOp) and type(node.op) in BINARY:
        # 递归计算左右两侧，如 2 + 3 * 4 会先得到右侧的 12，再计算加法。
        left, right = evaluate(node.left, depth + 1), evaluate(node.right, depth + 1)
        if isinstance(node.op, ast.Pow) and abs(right) > 12:
            raise ValueError("指数过大")
        value = BINARY[type(node.op)](left, right)
    elif isinstance(node, ast.UnaryOp) and type(node.op) in UNARY:
        # 一元运算指 +3、-3 这样的正负号，只有一个操作数。
        value = UNARY[type(node.op)](evaluate(node.operand, depth + 1))
    else:
        raise ValueError("表达式包含不允许的语法")
    if type(value) not in (int, float) or abs(value) > 10**100:
        raise ValueError("结果必须是范围内的实数")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("结果必须是有限数值")
    return value


def run_calculator(expression: str, *, context: ToolContext) -> ToolResult:
    # * 后面的 context 必须用命名参数传入；计算器保留它以统一工具调用接口。
    if len(expression) > 200:
        return ToolResult(ok=False, error="表达式过长")
    try:
        # mode="eval" 只允许单个表达式；ast.parse 只解析，evaluate 才按白名单求值。
        value = evaluate(ast.parse(expression, mode="eval").body)
    except (SyntaxError, TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
        return ToolResult(ok=False, error=f"无法计算: {exc}")
    return ToolResult(ok=True, data={"expression": expression, "result": value})


def run_search(query: str, *, context: ToolContext) -> ToolResult:
    query = query.strip().lower()
    if not query:
        return ToolResult(ok=False, error="query 不能为空")
    scored = []
    for document in DOCUMENTS:
        text = f"{document['title']} {document['text']}".lower()
        # split 按空白拆词；每命中一个词记 1 分，这是简单匹配而非向量检索。
        score = sum(term in text for term in query.split())
        if score:
            scored.append((score, document))
    # 按得分从高到低排序，最多取三条；下划线表示这里不再使用得分值。
    results = [item for _, item in sorted(scored, key=lambda row: -row[0])[:3]]
    return ToolResult(ok=True, data={"mock": True, "query": query, "results": results})


def run_weather(city: str, *, context: ToolContext) -> ToolResult:
    city = city.strip()
    value = WEATHER.get(city)
    if value is None:
        return ToolResult(ok=False, error=f"mock 数据中没有城市: {city}")
    # **value 将天气字典合并到返回数据；mock 提醒模型这是示例数据。
    return ToolResult(ok=True, data={"mock": True, "city": city, **value})


def run_todo(action: str, text: str = "", id: int | None = None,
             *, context: ToolContext) -> ToolResult:
    """只读写当前 Session，不使用全局 CURRENT_TODOS。"""
    todos = context.session.todos
    # todos 引用当前 Session 的列表，append 或修改 item 会直接改变会话内存状态。
    # Runtime 在工具返回后负责保存文件；工具本身不负责磁盘持久化。
    if action == "add":
        if not text.strip():
            return ToolResult(ok=False, error="add 操作需要非空 text")
        item = TodoItem(id=max((item.id for item in todos), default=0) + 1, text=text.strip())
        todos.append(item)
        return ToolResult(ok=True, data=item.to_dict())
    if action == "complete":
        if type(id) is not int:
            return ToolResult(ok=False, error="complete 操作需要整数 id")
        for item in todos:
            if item.id == id:
                item.done = True
                return ToolResult(ok=True, data=item.to_dict())
        return ToolResult(ok=False, error=f"待办不存在: {id}")
    # 正常经注册中心调用时，action 已由 enum 限制为 add/list/complete，剩下的是 list。
    return ToolResult(ok=True, data=[item.to_dict() for item in todos])


# ── 分发映射：增加工具时，补一个 Schema 和一个 handler ──

TOOL_HANDLERS = {
    "calculator": run_calculator, "search": run_search,
    "weather": run_weather, "todo": run_todo,
}


def default_registry() -> ToolRegistry:
    # 启动时将每份 Schema 与同名函数配对注册，得到 Runtime 可使用的工具集合。
    registry = ToolRegistry()
    for schema in TOOLS:
        registry.register(schema, TOOL_HANDLERS[schema["name"]])
    return registry
