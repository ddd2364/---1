if __name__ == "__main__":
    import _bootstrap

import json

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


if __name__ == "__main__":
    raise SystemExit(_bootstrap.run(__file__))
