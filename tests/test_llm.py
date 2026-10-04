if __name__ == "__main__":
    import _bootstrap

import io
import json
import urllib.error

import pytest

from agent_runtime.llm import LLMError, OpenAICompatibleClient


def test_deepseek_is_default_provider(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)

    client = OpenAICompatibleClient.from_env()

    assert client.endpoint == "https://api.deepseek.com/chat/completions"
    assert client.model == "deepseek-v4-flash"


def test_transient_http_error_retries_same_request(monkeypatch):
    requests, delays = [], []

    def urlopen(request, timeout):
        requests.append(request.data)
        if len(requests) == 1:
            raise urllib.error.HTTPError(request.full_url, 429, "limit", {"Retry-After": "0"}, io.BytesIO(b"limit"))
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": "OK"}}]}).encode())

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.setattr("agent_runtime.llm.time.sleep", delays.append)
    client = OpenAICompatibleClient("test", "https://example.invalid", "test")
    assert client.complete([{"role": "user", "content": "hello"}]) == "OK"
    assert requests[0] == requests[1]
    assert delays == [0]


@pytest.mark.parametrize("status,expected_calls", [(401, 1), (503, 3)])
def test_http_error_retry_is_bounded(monkeypatch, status, expected_calls):
    calls = []

    def urlopen(request, timeout):
        calls.append(request)
        raise urllib.error.HTTPError(request.full_url, status, "failure", {}, io.BytesIO(b"failure"))

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.setattr("agent_runtime.llm.time.sleep", lambda delay: None)
    client = OpenAICompatibleClient("test", "https://example.invalid", "test")
    with pytest.raises(LLMError):
        client.complete([{"role": "user", "content": "hello"}])
    assert len(calls) == expected_calls


def test_network_retry_exhaustion_is_reported(monkeypatch):
    def urlopen(request, timeout):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    monkeypatch.setattr("agent_runtime.llm.time.sleep", lambda delay: None)
    with pytest.raises(LLMError, match="offline"):
        OpenAICompatibleClient("test", "https://example.invalid", "test").complete([])


if __name__ == "__main__":
    raise SystemExit(_bootstrap.run(__file__))
