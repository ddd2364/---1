if __name__ == "__main__":
    import _bootstrap

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from agent_runtime.context import ContextManager
from agent_runtime.runtime import AgentRuntime
from agent_runtime.session import SessionStore
from agent_runtime.web import build_server


class ScriptedLLM:
    model = "deepseek-test"

    def __init__(self):
        self.responses = []

    def complete(self, messages):
        return self.responses.pop(0)


@pytest.fixture
def web_server(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    llm = ScriptedLLM()
    runtime = AgentRuntime(
        llm=llm,
        sessions=store,
        context=ContextManager(max_chars=100_000),
    )
    static_root = Path(__file__).parent.parent / "web"
    server = build_server(runtime, store, static_root, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", store, llm
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def request_json(url, path, method="GET", payload=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def test_serves_web_page_and_meta(web_server):
    url, _, _ = web_server
    with urllib.request.urlopen(url + "/", timeout=3) as response:
        html = response.read().decode("utf-8")
    assert "Minimal Agent Runtime" in html
    assert 'id="left-resizer"' in html
    assert 'id="right-resizer"' in html
    with urllib.request.urlopen(url + "/styles.css", timeout=3) as response:
        assert ".messages" in response.read().decode("utf-8")
    with urllib.request.urlopen(url + "/app.js", timeout=3) as response:
        assert "bootstrap()" in response.read().decode("utf-8")
    status, meta = request_json(url, "/api/meta")
    assert status == 200
    assert meta["provider"] == "DeepSeek"
    assert {tool["name"] for tool in meta["tools"]} == {
        "calculator", "search", "weather", "todo"
    }


def test_session_and_message_api(web_server):
    url, store, llm = web_server
    status, session = request_json(url, "/api/sessions", "POST", {})
    assert status == 201
    llm.responses.extend([
        '{"type":"tool_call","name":"calculator","arguments":{"expression":"20+22"}}',
        '{"type":"final","answer":"结果是 42。"}',
    ])
    status, payload = request_json(
        url,
        f"/api/sessions/{session['id']}/messages",
        "POST",
        {"message": "20+22 是多少？"},
    )
    assert status == 200
    assert payload["result"]["answer"] == "结果是 42。"
    assert payload["result"]["steps"] == 2
    assert any(item["event"] == "tool_finished" for item in payload["traces"])
    run_ids = {item.get("run_id") for item in payload["traces"]}
    assert None not in run_ids
    assert len(run_ids) == 1
    assert store.load(session["id"]).messages[-1].content == "结果是 42。"


def test_web_api_validates_input(web_server):
    url, _, _ = web_server
    _, session = request_json(url, "/api/sessions", "POST", {})
    with pytest.raises(urllib.error.HTTPError) as error:
        request_json(
            url,
            f"/api/sessions/{session['id']}/messages",
            "POST",
            {"message": ""},
        )
    assert error.value.code == 400


if __name__ == "__main__":
    raise SystemExit(_bootstrap.run(__file__))
