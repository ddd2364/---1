if __name__ == "__main__":
    import _bootstrap

from agent_runtime.llm import OpenAICompatibleClient


def test_deepseek_is_default_provider(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    monkeypatch.delenv("DEEPSEEK_MODEL", raising=False)

    client = OpenAICompatibleClient.from_env()

    assert client.endpoint == "https://api.deepseek.com/chat/completions"
    assert client.model == "deepseek-v4-flash"


if __name__ == "__main__":
    raise SystemExit(_bootstrap.run(__file__))
