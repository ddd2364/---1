from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol


class LLMError(RuntimeError):
    pass


class LLMClient(Protocol):
    def complete(self, messages: list[dict[str, str]]) -> str: ...


def load_dotenv(path: str = ".env") -> None:
    """Small dotenv reader; existing process variables always win."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, value)


class OpenAICompatibleClient:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 60,
    ) -> None:
        if not api_key or not base_url or not model:
            raise ValueError("LLM api_key、base_url 和 model 均不能为空")
        self.api_key = api_key
        self.endpoint = self._endpoint(base_url)
        self.model = model
        self.timeout = timeout

    @staticmethod
    def _endpoint(base_url: str) -> str:
        value = base_url.rstrip("/")
        if value.endswith("/chat/completions"):
            return value
        return value + "/chat/completions"

    @classmethod
    def from_env(cls) -> "OpenAICompatibleClient":
        load_dotenv()
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise ValueError("缺少 DEEPSEEK_API_KEY，请参考 .env.example")
        return cls(
            api_key=api_key,
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        )

    def complete(self, messages: list[dict[str, str]]) -> str:
        payload = json.dumps(
            {"model": self.model, "messages": messages, "temperature": 0.1},
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise LLMError(f"LLM HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise LLMError(f"LLM 请求失败: {exc}") from exc
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("LLM 返回结构不符合 OpenAI-compatible 格式") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMError("LLM 返回了空内容")
        return content
