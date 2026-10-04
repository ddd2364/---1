if __name__ == "__main__":
    import _bootstrap

from agent_runtime.context import ContextManager
from agent_runtime.models import Message, Session, TodoItem
from agent_runtime.tools import default_registry


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


def test_compaction_keeps_tool_call_and_result_together():
    session = Session(id="s", messages=[
        Message(role="user", content="old " * 100),
        Message(role="assistant", name="weather", content='{"name":"weather","arguments":{"city":"北京"}}'),
        Message(role="tool", name="weather", content='{"mock":true}'),
        Message(role="assistant", content="北京是示例天气。"),
    ])
    manager = ContextManager(max_chars=100, keep_recent=2)
    assert manager.maybe_compact(session, SummaryLLM())
    assert session.messages[0].role == "assistant"
    assert session.messages[0].name == "weather"
    assert session.messages[1].role == "tool"


def test_memory_recall_uses_current_session_state_after_compaction():
    session = Session(id="s", todos=[TodoItem(id=1, text="带伞", done=True)],
                      messages=[Message(role="user", content="old " * 100) for _ in range(5)])
    manager = ContextManager(max_chars=100, keep_recent=2)
    manager.maybe_compact(session, SummaryLLM())
    messages = manager.build(session, default_registry())
    memory = next(m for m in messages if "<session_memory>" in m["content"])
    assert '"done": true' in memory["content"]
    assert "带伞" in memory["content"]
    assert memory["role"] == "user"
    other = manager.build(Session(id="other"), default_registry())
    assert all("带伞" not in m["content"] for m in other)


if __name__ == "__main__":
    raise SystemExit(_bootstrap.run(__file__))
