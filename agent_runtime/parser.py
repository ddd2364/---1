# 模块职责：把模型生成的字符串转换为 AgentDecision，不在这里执行任何工具。
# 当前使用正文 JSON 协议，tool_call 是本项目约定的字段值。
from __future__ import annotations

import json
import re
from typing import Any

from .models import AgentDecision


class DecisionParseError(ValueError):
    # 专用异常便于 Runtime 识别格式问题，并请求模型纠正一次。
    pass


def parse_decision(raw: str) -> AgentDecision:
    """把模型文本严格转换为运行时可执行的结构化决策。"""

    text = raw.strip()
    # 容忍模型常见的 ```json 包裹，但内部协议仍要求顶层必须是 JSON object。
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        # group(1) 取出三反引号中间的正文，不把 Markdown 标记交给 JSON 解析器。
        text = fenced.group(1).strip()
    try:
        value: Any = json.loads(text)
    except json.JSONDecodeError:
        # 兼容 JSON 前后夹带少量说明文字的情况；更复杂的错误交给上层修复流程。
        start, end = text.find("{"), text.rfind("}")
        # 这只是容错提取；取出的内容仍必须通过 json.loads 和下面的字段校验。
        if start < 0 or end <= start:
            raise DecisionParseError("输出中没有 JSON object")
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise DecisionParseError(f"JSON 无法解析: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise DecisionParseError("顶层输出必须是 JSON object")
    decision_type = value.get("type")
    reason = value.get("reasoning_summary", "")
    if not isinstance(reason, str):
        raise DecisionParseError("reasoning_summary 必须是字符串")
    # 分支内逐项校验，防止格式正确但字段类型错误的数据进入执行层。
    if decision_type == "tool_call":
        # 这里只检查决策结构；工具是否存在、具体参数是否合法由 ToolRegistry 检查。
        name, arguments = value.get("name"), value.get("arguments")
        if not isinstance(name, str) or not name:
            raise DecisionParseError("tool_call 缺少 name")
        if not isinstance(arguments, dict):
            raise DecisionParseError("tool_call.arguments 必须是 object")
        return AgentDecision(
            type="tool_call", reasoning_summary=reason, name=name, arguments=arguments
        )
    if decision_type == "final":
        # 最终答案必须是非空文本，避免把没有内容的回复当作成功完成。
        answer = value.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            raise DecisionParseError("final 缺少非空 answer")
        return AgentDecision(type="final", reasoning_summary=reason, answer=answer)
    raise DecisionParseError("type 必须是 tool_call 或 final")
