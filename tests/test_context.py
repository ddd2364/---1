if __name__ == "__main__":
    import _bootstrap

from agent_runtime.context import ContextManager
from agent_runtime.models import Message, Session


class SummaryLLM:
    def complete(self, messages):
        return "用户正在构建 Agent；未完成事项：补测试。"


def test_context_compaction_keeps_recent_messages():
    session = Session(
        id="s",
        messages=[Message(role="user", content=f"message-{i}-" + "x" * 30) for i in range(10)],
    )
    manager = ContextManager(max_chars=100, keep_recent=3)
    assert manager.maybe_compact(session, SummaryLLM())
    assert len(session.messages) == 3
    assert "未完成事项" in session.summary
    assert session.messages[0].content.startswith("message-7")


def test_compaction_has_fallback_when_llm_fails():
    class BrokenLLM:
        def complete(self, messages):
            raise RuntimeError("offline")

    session = Session(
        id="s", messages=[Message(role="user", content="important " * 20) for _ in range(5)]
    )
    manager = ContextManager(max_chars=50, keep_recent=2)
    assert manager.maybe_compact(session, BrokenLLM())
    assert session.summary
    assert len(session.messages) == 2


if __name__ == "__main__":
    raise SystemExit(_bootstrap.run(__file__))
