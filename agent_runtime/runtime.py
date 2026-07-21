from __future__ import annotations

import json
import uuid
from dataclasses import dataclass

from .context import ContextManager
from .llm import LLMClient, LLMError
from .models import AgentDecision, Message, Session
from .parser import DecisionParseError, parse_decision
from .session import SessionStore
from .tools import ToolContext, ToolRegistry, default_registry
from .trace import TraceLogger


@dataclass
class RunResult:
    answer: str
    steps: int
    error: str | None = None


class AgentRuntime:
    def __init__(
        self,
        llm: LLMClient,
        sessions: SessionStore,
        registry: ToolRegistry | None = None,
        context: ContextManager | None = None,
        traces: TraceLogger | None = None,
        max_steps: int = 8,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps 必须大于 0")
        self.llm = llm
        self.sessions = sessions
        self.registry = registry or default_registry()
        self.context = context or ContextManager()
        self.traces = traces or TraceLogger(sessions.root.parent / "traces")
        self.max_steps = max_steps

    def run(self, session_id: str, user_input: str) -> RunResult:
        if not user_input.strip():
            return RunResult(answer="请输入非空问题。", steps=0, error="empty_input")
        session = self.sessions.load(session_id)
        run_id = uuid.uuid4().hex
        session.messages.append(Message(role="user", content=user_input.strip()))
        self.sessions.save(session)
        self.traces.log(
            session_id,
            "run_started",
            run_id=run_id,
            input_chars=len(user_input),
            input_preview=user_input.strip()[:80],
        )

        if self.context.maybe_compact(session, self.llm):
            self.sessions.save(session)
            self.traces.log(session_id, "context_compacted", run_id=run_id)

        for step in range(1, self.max_steps + 1):
            try:
                raw = self.llm.complete(self.context.build(session, self.registry))
                decision = self._parse_with_repair(session_id, run_id, raw, session)
            except (LLMError, DecisionParseError, ValueError) as exc:
                message = f"Agent 暂时无法完成请求：{exc}"
                session.messages.append(Message(role="assistant", content=message))
                self.sessions.save(session)
                self.traces.log(
                    session_id, "run_failed", run_id=run_id, step=step, error=str(exc)
                )
                return RunResult(answer=message, steps=step, error=str(exc))

            self.traces.log(
                session_id,
                "decision",
                run_id=run_id,
                step=step,
                type=decision.type,
                reasoning_summary=decision.reasoning_summary,
                tool=decision.name,
            )
            if decision.type == "final":
                answer = decision.answer or ""
                session.messages.append(Message(role="assistant", content=answer))
                self.sessions.save(session)
                self.traces.log(session_id, "run_finished", run_id=run_id, step=step)
                return RunResult(answer=answer, steps=step)

            result = self.registry.execute(
                decision.name or "", decision.arguments, ToolContext(session=session)
            )
            tool_content = json.dumps(result.to_dict(), ensure_ascii=False, default=str)
            session.messages.append(
                Message(role="tool", name=decision.name, content=tool_content)
            )
            self.sessions.save(session)
            self.traces.log(
                session_id,
                "tool_finished",
                run_id=run_id,
                step=step,
                tool=decision.name,
                ok=result.ok,
                error=result.error,
            )

        message = f"已达到单次请求最大执行步数（{self.max_steps}），为避免无限循环已停止。"
        session.messages.append(Message(role="assistant", content=message))
        self.sessions.save(session)
        self.traces.log(
            session_id, "max_steps_reached", run_id=run_id, max_steps=self.max_steps
        )
        return RunResult(answer=message, steps=self.max_steps, error="max_steps_reached")

    def _parse_with_repair(
        self, session_id: str, run_id: str, raw: str, session: Session
    ) -> AgentDecision:
        try:
            return parse_decision(raw)
        except DecisionParseError as first_error:
            self.traces.log(
                session_id, "parse_repair", run_id=run_id, error=str(first_error)
            )
            repair_messages = self.context.build(session, self.registry) + [
                {"role": "assistant", "content": raw[:4000]},
                {
                    "role": "user",
                    "content": (
                        "上一个输出不符合协议。请只重新输出一个合法 JSON object，"
                        "type 必须是 tool_call 或 final，不要输出 Markdown。"
                    ),
                },
            ]
            repaired = self.llm.complete(repair_messages)
            try:
                return parse_decision(repaired)
            except DecisionParseError as second_error:
                raise DecisionParseError(
                    f"模型连续两次返回非法格式；首次: {first_error}；修复后: {second_error}"
                ) from second_error
