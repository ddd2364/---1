from __future__ import annotations

import json
import re
from typing import Any

from .models import AgentDecision


class DecisionParseError(ValueError):
    pass


def parse_decision(raw: str) -> AgentDecision:
    text = raw.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1).strip()
    try:
        value: Any = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
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
    if decision_type == "tool_call":
        name, arguments = value.get("name"), value.get("arguments")
        if not isinstance(name, str) or not name:
            raise DecisionParseError("tool_call 缺少 name")
        if not isinstance(arguments, dict):
            raise DecisionParseError("tool_call.arguments 必须是 object")
        return AgentDecision(
            type="tool_call", reasoning_summary=reason, name=name, arguments=arguments
        )
    if decision_type == "final":
        answer = value.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            raise DecisionParseError("final 缺少非空 answer")
        return AgentDecision(type="final", reasoning_summary=reason, answer=answer)
    raise DecisionParseError("type 必须是 tool_call 或 final")

