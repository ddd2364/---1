if __name__ == "__main__":
    import _bootstrap

import json
import threading
from concurrent.futures import ThreadPoolExecutor

from agent_runtime.llm import LLMError

from agent_runtime.context import ContextManager
from agent_runtime.runtime import AgentRuntime
from agent_runtime.session import SessionStore


class ScriptedLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages):
        self.calls.append(messages)
        if not self.responses:
            raise AssertionError("unexpected LLM call")
        return self.responses.pop(0)


def make_runtime(tmp_path, responses, max_steps=8):
    store = SessionStore(tmp_path / "sessions")
    llm = ScriptedLLM(responses)
    runtime = AgentRuntime(
        llm=llm,
        sessions=store,
        max_steps=max_steps,
        context=ContextManager(max_chars=100_000),
    )
    return runtime, store, llm


def test_direct_answer(tmp_path):
    runtime, store, _ = make_runtime(
        tmp_path, ['{"type":"final","reasoning_summary":"可直接回答","answer":"你好！"}']
    )
    session = store.create()
    result = runtime.run(session.id, "你好")
    assert result.answer == "你好！"
    assert result.steps == 1
    assert [message.role for message in store.load(session.id).messages] == ["user", "assistant"]


def test_tool_result_returns_to_loop(tmp_path):
    runtime, store, llm = make_runtime(
        tmp_path,
        [
            '{"type":"tool_call","name":"calculator","arguments":{"expression":"6*7"}}',
            '{"type":"final","answer":"结果是 42。"}',
        ],
    )
    session = store.create()
    result = runtime.run(session.id, "六乘七是多少")
    assert result.answer == "结果是 42。"
    saved = store.load(session.id)
    assert any(message.role == "tool" and "42" in message.content for message in saved.messages)
    assert "<tool_result name=calculator>" in llm.calls[1][-1]["content"]


def test_multiple_tools_and_session_todo_persistence(tmp_path):
    runtime, store, _ = make_runtime(
        tmp_path,
        [
            '{"type":"tool_call","name":"weather","arguments":{"city":"北京"}}',
            '{"type":"tool_call","name":"todo","arguments":{"action":"add","text":"带伞"}}',
            '{"type":"final","answer":"mock 天气已查询，并记下待办。"}',
        ],
    )
    session = store.create()
    result = runtime.run(session.id, "查北京天气并提醒我带伞")
    assert result.steps == 3
    assert store.load(session.id).todos[0].text == "带伞"


def test_invalid_output_gets_one_repair(tmp_path):
    runtime, store, llm = make_runtime(
        tmp_path, ["I forgot JSON", '{"type":"final","answer":"已修复。"}']
    )
    session = store.create()
    assert runtime.run(session.id, "测试").answer == "已修复。"
    assert len(llm.calls) == 2


def test_max_steps_stops_infinite_tool_loop(tmp_path):
    call = '{"type":"tool_call","name":"todo","arguments":{"action":"list"}}'
    runtime, store, _ = make_runtime(tmp_path, [call, call], max_steps=2)
    session = store.create()
    result = runtime.run(session.id, "循环")
    assert result.error == "max_steps_reached"
    assert result.steps == 2


def test_follow_up_contains_previous_history(tmp_path):
    runtime, store, llm = make_runtime(
        tmp_path,
        [
            '{"type":"final","answer":"记住了，你喜欢蓝色。"}',
            '{"type":"final","answer":"你喜欢蓝色。"}',
        ],
    )
    session = store.create()
    runtime.run(session.id, "我喜欢蓝色")
    runtime.run(session.id, "我喜欢什么颜色？")
    contents = [message["content"] for message in llm.calls[1]]
    assert "我喜欢蓝色" in contents
    assert "记住了，你喜欢蓝色。" in contents


def test_tool_call_arguments_and_trace_are_preserved(tmp_path):
    runtime, store, llm = make_runtime(tmp_path, [
        '{"type":"tool_call","reasoning_summary":"用工具核对","name":"calculator","arguments":{"expression":"6*7"}}',
        '{"type":"final","answer":"42"}',
    ])
    session = store.create()
    runtime.run(session.id, "计算6*7")
    action = json.loads(llm.calls[1][-2]["content"])
    assert action == {"type": "tool_call", "name": "calculator", "arguments": {"expression": "6*7"}}
    assert "用工具核对" not in json.dumps(llm.calls[1], ensure_ascii=False)
    event = next(e for e in runtime.traces.read_last(session.id) if e["event"] == "tool_finished")
    assert event["arguments"] == {"expression": "6*7"}
    assert event["result"]["data"]["result"] == 42
    assert event["duration_ms"] >= 0


def test_two_windows_resume_with_independent_todos(tmp_path):
    runtime, store, llm = make_runtime(tmp_path, [
        '{"type":"tool_call","name":"weather","arguments":{"city":"北京"}}',
        '{"type":"tool_call","name":"todo","arguments":{"action":"add","text":"带伞"}}',
        '{"type":"final","answer":"北京 mock 天气已查，已记带伞。"}',
        '{"type":"tool_call","name":"todo","arguments":{"action":"add","text":"写周报"}}',
        '{"type":"final","answer":"周报：完成开发；下周补测试。已记待办。"}',
        '{"type":"tool_call","name":"todo","arguments":{"action":"complete","id":1}}',
        '{"type":"final","answer":"带伞已完成。"}',
    ])
    a, b = store.create(), store.create()
    runtime.run(a.id, "查北京天气并记待办带伞")
    runtime.run(b.id, "帮我写周报，并记待办写周报")
    # 新 Runtime 从磁盘恢复，而不是依赖上次请求的内存对象。
    restored = SessionStore(store.root)
    resumed = AgentRuntime(llm, restored)
    resumed.run(a.id, "把刚才那个待办标记完成")
    assert restored.load(a.id).todos[0].done
    assert restored.load(b.id).todos[0].text == "写周报"
    assert not restored.load(b.id).todos[0].done
    assert "写周报" not in json.dumps(llm.calls[-1], ensure_ascii=False)


def test_errors_return_to_model_or_user_without_unbounded_retry(tmp_path):
    runtime, store, llm = make_runtime(tmp_path, [
        '{"type":"tool_call","name":"calculator","arguments":{"expression":"1/0"}}',
        '{"type":"final","answer":"不能除以零。"}',
        'not JSON', 'still not JSON',
    ])
    session = store.create()
    assert runtime.run(session.id, "计算1/0").answer == "不能除以零。"
    assert '"ok": false' in llm.calls[1][-1]["content"]
    assert runtime.run(session.id, "测试坏格式").error
    assert len(llm.calls) == 4

    class OfflineLLM:
        def complete(self, messages):
            raise LLMError("offline")

    runtime.llm = OfflineLLM()
    assert runtime.run(session.id, "断网").error == "offline"
    assert "offline" in store.load(session.id).messages[-1].content


def test_compaction_runs_between_tool_steps(tmp_path):
    from agent_runtime.models import ToolResult
    from agent_runtime.tools import ToolRegistry

    class GrowingLLM:
        def __init__(self):
            self.steps = 0
            self.summaries = 0

        def complete(self, messages):
            if messages[0]["content"].startswith("压缩对话"):
                self.summaries += 1
                return "用户目标：读取大结果后回答。"
            self.steps += 1
            if self.steps < 4:
                return '{"type":"tool_call","name":"large","arguments":{}}'
            return '{"type":"final","answer":"完成"}'

    registry = ToolRegistry()
    registry.register({"name": "large", "description": "large output", "parameters": {}},
                      lambda context: ToolResult(ok=True, data="x" * 900))
    store = SessionStore(tmp_path / "sessions")
    llm = GrowingLLM()
    runtime = AgentRuntime(llm, store, registry, ContextManager(max_chars=1200, keep_recent=2))
    assert runtime.run(store.create().id, "读取大结果后回答").answer == "完成"
    assert llm.summaries >= 1


def test_same_session_serializes_but_other_session_can_run(tmp_path):
    entered, release = threading.Event(), threading.Event()

    class BlockingLLM:
        def complete(self, messages):
            if messages[-1]["content"] == "first":
                entered.set()
                assert release.wait(5)
            return '{"type":"final","answer":"done"}'

    store = SessionStore(tmp_path / "sessions")
    runtime = AgentRuntime(BlockingLLM(), store)
    a, b = store.create(), store.create()
    with ThreadPoolExecutor(max_workers=3) as pool:
        first = pool.submit(runtime.run, a.id, "first")
        assert entered.wait(3)
        second = pool.submit(runtime.run, a.id, "second")
        try:
            other = pool.submit(runtime.run, b.id, "other")
            assert other.result(timeout=3).answer == "done"
            assert not second.done()
        finally:
            release.set()
        assert first.result(timeout=3).answer == "done"
        assert second.result(timeout=3).answer == "done"
    history = store.load(a.id).messages
    assert [m.content for m in history] == ["first", "done", "second", "done"]


if __name__ == "__main__":
    raise SystemExit(_bootstrap.run(__file__))
