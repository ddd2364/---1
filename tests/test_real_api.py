if __name__ == "__main__":
    import _bootstrap

import os

import pytest

from agent_runtime.llm import LLMError, OpenAICompatibleClient
from agent_runtime.runtime import AgentRuntime
from agent_runtime.session import SessionStore


@pytest.mark.skipif(os.getenv("RUN_REAL_LLM_TEST") != "1", reason="需要真实 API 和显式开启")
def test_real_api_returns_content():
    client = OpenAICompatibleClient.from_env()
    try:
        value = client.complete([{"role": "user", "content": "只回复 OK"}])
    except LLMError as exc:
        pytest.fail(str(exc), pytrace=False)
    assert value.strip()


@pytest.mark.skipif(os.getenv("RUN_REAL_LLM_TEST") != "1", reason="需要真实 API 和显式开启")
def test_real_api_agent_tool_loop(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    runtime = AgentRuntime(OpenAICompatibleClient.from_env(), store, max_steps=4)
    session = store.create()
    result = runtime.run(session.id, "请调用 calculator 计算 (125+75)*3，再告诉我结果。")
    assert result.error is None
    assert "600" in result.answer
    events = runtime.traces.read_last(session.id)
    assert any(e["event"] == "tool_finished" and e["tool"] == "calculator"
               and e["ok"] and e["result"]["data"]["result"] == 600 for e in events)


if __name__ == "__main__":
    raise SystemExit(_bootstrap.run(__file__))
