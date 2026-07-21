if __name__ == "__main__":
    import _bootstrap

import os

import pytest

from agent_runtime.llm import OpenAICompatibleClient


@pytest.mark.skipif(os.getenv("RUN_REAL_LLM_TEST") != "1", reason="需要真实 API 和显式开启")
def test_real_api_returns_content():
    client = OpenAICompatibleClient.from_env()
    value = client.complete([{"role": "user", "content": "只回复 OK"}])
    assert value.strip()


if __name__ == "__main__":
    raise SystemExit(_bootstrap.run(__file__))
