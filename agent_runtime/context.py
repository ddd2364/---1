from __future__ import annotations

import json

from .llm import LLMClient
from .models import Message, Session
from .tools import ToolRegistry


SYSTEM_PROMPT = """你是一个最小可用 Agent。你可以直接回答，也可以自主调用工具。
必须只输出一个 JSON object，不要使用 Markdown：
1. 调用工具：{{"type":"tool_call","reasoning_summary":"简短决策依据","name":"工具名","arguments":{{}}}}
2. 最终回答：{{"type":"final","reasoning_summary":"简短决策依据","answer":"给用户的回答"}}

规则：
- 只可调用工具清单中的工具，并严格遵守参数 Schema。
- 收到 tool_result 后判断是否需要继续调用工具；否则返回 final。
- 不要伪造工具结果。mock 工具结果必须如实告知用户。
- reasoning_summary 只写一句简短决策依据，不输出详细思维链。

工具清单：
{tool_schemas}
"""


class ContextManager:
    def __init__(self, max_chars: int = 24000, keep_recent: int = 8) -> None:
        self.max_chars = max_chars
        self.keep_recent = keep_recent

    def build(self, session: Session, registry: ToolRegistry) -> list[dict[str, str]]:
        tools_json = json.dumps(registry.schemas(), ensure_ascii=False, indent=2)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": SYSTEM_PROMPT.format(tool_schemas=tools_json)}
        ]
        if session.summary:
            messages.append(
                {"role": "system", "content": "较早对话摘要（仅作上下文）：\n" + session.summary}
            )
        for item in session.messages:
            messages.append(self._api_message(item))
        return messages

    @staticmethod
    def _api_message(message: Message) -> dict[str, str]:
        if message.role == "tool":
            return {
                "role": "user",
                "content": f"<tool_result name={message.name}>\n{message.content}\n</tool_result>",
            }
        return {"role": message.role, "content": message.content}

    def maybe_compact(self, session: Session, llm: LLMClient) -> bool:
        total = len(session.summary) + sum(len(message.content) for message in session.messages)
        if total <= self.max_chars or len(session.messages) <= self.keep_recent:
            return False
        old = session.messages[: -self.keep_recent]
        recent = session.messages[-self.keep_recent :]
        transcript = "\n".join(
            f"{item.role}{f'({item.name})' if item.name else ''}: {item.content}" for item in old
        )
        prompt = [
            {
                "role": "system",
                "content": (
                    "压缩对话。只返回简洁纯文本摘要，保留用户目标、明确事实、偏好、"
                    "承诺、未完成事项和重要工具结论；不要添加不存在的信息。"
                ),
            },
            {
                "role": "user",
                "content": f"已有摘要:\n{session.summary or '无'}\n\n需压缩消息:\n{transcript}",
            },
        ]
        try:
            summary = llm.complete(prompt).strip()
            if not summary:
                raise ValueError("空摘要")
        except Exception:
            summary = self._fallback_summary(session.summary, old)
        session.summary = summary[: self.max_chars // 2]
        session.messages = recent
        return True

    @staticmethod
    def _fallback_summary(previous: str, messages: list[Message]) -> str:
        lines = [previous] if previous else []
        lines.extend(f"{item.role}: {item.content[:300]}" for item in messages)
        return "\n".join(lines)[-6000:]
