# 模块职责：把会话、上下文、模型、工具和日志连接成完整的 Agent 循环。
# 对应参考 s01；错误恢复借鉴 s11。阅读顺序：run → _run_turn → agent_loop。
from __future__ import annotations

import json
import uuid
from time import perf_counter
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
    """一次 Agent 运行的对外结果，不暴露内部决策和工具调用细节。"""

    # dataclass 自动生成构造方法；例如 RunResult(answer="42", steps=2)。
    # steps 统计主循环的决策步骤，error 为 None 表示正常返回。
    answer: str
    steps: int
    error: str | None = None


class AgentRuntime:
    """协调模型决策、工具执行、会话持久化和链路追踪的主运行时。"""

    def __init__(
        self,
        llm: LLMClient,
        sessions: SessionStore,
        registry: ToolRegistry | None = None,
        context: ContextManager | None = None,
        traces: TraceLogger | None = None,
        max_steps: int = 8,
    ) -> None:
        # 从外部传入依赖：实际运行用真实 LLM，测试可以传入返回固定答案的 LLM。
        # 参数默认 None 时才创建默认组件，避免把组件实例写成共享的默认参数。
        if max_steps < 1:
            raise ValueError("max_steps 必须大于 0")
        self.llm = llm
        self.sessions = sessions
        self.registry = registry or default_registry()
        self.context = context or ContextManager()
        self.traces = traces or TraceLogger(sessions.root.parent / "traces")
        self.max_steps = max_steps

    def run(self, session_id: str, user_input: str) -> RunResult:
        """在指定会话内执行一轮完整的“模型决策—工具调用”循环。"""

        if not user_input.strip():
            return RunResult(answer="请输入非空问题。", steps=0, error="empty_input")
        # 锁覆盖 load → loop → save，避免两个请求读到同一份旧 Session 后互相覆盖。
        # 同一 Session 的后一条请求要等前一条结束，防止两份旧状态互相覆盖。
        # with 内即使 return 或抛出异常，也会退出上下文并释放锁；不同 Session 用不同锁。
        with self.sessions.turn(session_id):
            return self._run_turn(session_id, user_input.strip())

    def _run_turn(self, session_id: str, user_input: str) -> RunResult:
        session = self.sessions.load(session_id)
        # session_id 标识整段聊天；run_id 标识其中一次用户请求，用来串起本次所有日志。
        # uuid4() 生成随机 UUID，.hex 把它转为不带连字符的字符串。
        run_id = uuid.uuid4().hex
        # 先持久化用户输入，确保后续即使模型请求失败，对话记录也不会丢失。
        session.messages.append(Message(role="user", content=user_input.strip()))
        self.sessions.save(session)
        self.traces.log(
            session_id,
            "run_started",
            run_id=run_id,
            input_chars=len(user_input),
            input_preview=user_input.strip()[:80],
        )

        return self.agent_loop(session, run_id)

    # ── 主循环：准备上下文 → LLM 决策 → final / tool → 回填 → 下一轮 ──

    def agent_loop(self, session: Session, run_id: str) -> RunResult:
        session_id = session.id
        # range 不包含右端点，因此这里依次执行 1 到 max_steps。
        # 一步做一次决策：选择一个工具，或给出最终答案。
        for step in range(1, self.max_steps + 1):
            # s08：在每次模型请求前检查，而非只在用户输入时压缩一次。
            if self.context.maybe_compact(session, self.llm):
                self.sessions.save(session)
                # 保存压缩后的状态，并记录发生压缩的步骤。
                self.traces.log(session_id, "context_compacted", run_id=run_id, step=step)
            try:
                # build 组装系统协议、工具说明、记忆和历史；complete 发送它们并返回文本。
                raw = self.llm.complete(self.context.build(session, self.registry))
                # 文本通过解析后才成为可执行的 AgentDecision；格式错误时尝试修复一次。
                decision = self._parse_with_repair(session_id, run_id, raw, session)
            except (LLMError, DecisionParseError, ValueError) as exc:
                message = f"Agent 暂时无法完成请求：{exc}"
                session.messages.append(Message(role="assistant", content=message))
                self.sessions.save(session)
                self.traces.log(
                    session_id, "run_failed", run_id=run_id, step=step, error=str(exc)
                )
                return RunResult(answer=message, steps=step, error=str(exc))

            # reasoning_summary 只写入日志，不作为后续历史消息回填给模型。
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
                # return 直接结束整个循环；前端只需读取 RunResult 中的答案和状态。
                answer = decision.answer or ""
                session.messages.append(Message(role="assistant", content=answer))
                self.sessions.save(session)
                self.traces.log(session_id, "run_finished", run_id=run_id, step=step)
                return RunResult(answer=answer, steps=step)

            # s01：先记录模型的调用，再记录工具结果；只保留动作，不回填思考摘要。
            action = {"type": "tool_call", "name": decision.name, "arguments": decision.arguments}
            session.messages.append(Message(
                role="assistant", name=decision.name,
                content=json.dumps(action, ensure_ascii=False),
            ))
            # log 的前两个参数是会话和事件名，后面的命名参数是这条事件的附加字段。
            # 例如：本次 run 的第 1 步调用 calculator，参数为 {"expression": "6*7"}。
            self.traces.log(session_id, "tool_started", run_id=run_id, step=step,
                            tool=decision.name, arguments=decision.arguments)
            # perf_counter 适合计算时间差；本段计时还包含后面的序列化和会话保存。
            started = perf_counter()
            # 模型只提供名称和参数；真正执行 Python 函数的是 registry。
            # ToolContext 把当前 Session 交给工具，使 todo 只修改当前会话。
            result = self.registry.execute(
                decision.name or "", decision.arguments, ToolContext(session=session)
            )
            # 工具结果作为下一轮模型可见的上下文写回会话，形成闭环。
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
                arguments=decision.arguments,
                result=result.to_dict(),
                duration_ms=round((perf_counter() - started) * 1000, 2),
            )
            # 工具成功或失败都已写成消息；自然进入下一步，让模型根据结果再作决策。

        # max_steps 是最后一道防线，避免模型持续调用工具造成无限循环和费用失控。
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
        """解析模型协议；首次失败时额外给模型一次纠正格式的机会。"""

        try:
            return parse_decision(raw)
        except DecisionParseError as first_error:
            self.traces.log(
                session_id, "parse_repair", run_id=run_id, error=str(first_error)
            )
            # 限制原始错误输出长度，避免修复请求反而显著膨胀上下文。
            # + 创建临时消息列表；错误输出和纠正指令不会永久加入 session.messages。
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
            # 每次决策最多纠正一次；再次失败会向外抛出，由 agent_loop 返回错误。
            try:
                return parse_decision(repaired)
            except DecisionParseError as second_error:
                raise DecisionParseError(
                    f"模型连续两次返回非法格式；首次: {first_error}；修复后: {second_error}"
                ) from second_error
