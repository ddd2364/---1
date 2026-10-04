# 模块职责：读取连接配置，通过 HTTP 调用模型，并把响应统一转换为字符串。
# 对应 s11 的部分重试策略；Agent 的工具循环由 runtime.py 控制。
from __future__ import annotations

import json
import os
import random
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol


class LLMError(RuntimeError):
    pass


def retry_delay(attempt: int, retry_after: str | None = None) -> float:
    """s11：指数退避 + 抖动；数字形式的 Retry-After 优先，最多等待 30 秒。"""
    try:
        if retry_after is not None:
            value = float(retry_after)
            if 0 <= value <= 30:
                return value
    except ValueError:
        pass
    # attempt 从 0 开始，基础等待为 0.5、1、2…秒；随机抖动减少同时重试的拥挤。
    base = min(0.5 * 2**attempt, 8)
    return base + random.uniform(0, base * 0.25)


class LLMClient(Protocol):
    """运行时依赖的最小模型接口，便于替换供应商或注入测试桩。"""

    # Protocol 描述所需接口；真实客户端和测试替身都只需提供兼容的 complete 方法。
    def complete(self, messages: list[dict[str, str]]) -> str: ...


def load_dotenv(path: str = ".env") -> None:
    """读取简单的 dotenv 配置；已有进程环境变量拥有更高优先级。"""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        # 只按第一个等号拆分，保留值中可能存在的等号；这是简单解析器，不展开变量。
        key, value = key.strip(), value.strip().strip("\"'")
        if key:
            # setdefault 不覆盖进程里已有的同名变量，允许启动时临时指定配置。
            os.environ.setdefault(key, value)


class OpenAICompatibleClient:
    """通过标准库调用 OpenAI-compatible Chat Completions 接口。"""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 60,
        max_retries: int = 2,
    ) -> None:
        if not api_key or not base_url or not model:
            raise ValueError("LLM api_key、base_url 和 model 均不能为空")
        self.api_key = api_key
        self.endpoint = self._endpoint(base_url)
        self.model = model
        self.timeout = timeout
        if max_retries < 0:
            raise ValueError("max_retries 不能小于 0")
        self.max_retries = max_retries

    @staticmethod
    def _endpoint(base_url: str) -> str:
        # 兼容用户填写 API 根地址或完整的 /chat/completions 地址。
        value = base_url.rstrip("/")
        if value.endswith("/chat/completions"):
            return value
        return value + "/chat/completions"

    @classmethod
    def from_env(cls) -> "OpenAICompatibleClient":
        # 工厂方法：从配置创建实例，使启动代码不用逐项传 API Key、地址和模型。
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
        """发送一次非流式补全请求，并统一转换网络和响应格式错误。"""

        # HTTP 请求体是 UTF-8 字节；工具说明已包含在 messages 中。
        # 这里不使用供应商原生 tools 字段，模型按系统提示输出自定义 JSON 决策。
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
        # 首次请求加上最多 max_retries 次重试；默认 2 次重试意味着最多尝试 3 次。
        for attempt in range(self.max_retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    body = json.loads(response.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as exc:
                # HTTPError 是 URLError 的子类，要先捕获才能针对状态码区别处理。
                detail = exc.read().decode("utf-8", errors="replace")[:500]
                if exc.code in (429, 500, 502, 503, 504, 529) and attempt < self.max_retries:
                    time.sleep(retry_delay(attempt, exc.headers.get("Retry-After")))
                    continue
                # 鉴权失败等非重试状态，以及重试耗尽的情况，统一交给 Runtime 处理。
                raise LLMError(f"LLM HTTP {exc.code}: {detail}") from None
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt < self.max_retries:
                    time.sleep(retry_delay(attempt))
                    continue
                # urllib 的原始堆栈可能包含 Authorization；对外只保留错误摘要。
                raise LLMError(f"LLM 请求失败: {exc}") from None
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise LLMError(f"LLM 响应无法解析: {exc}") from exc
        # 在客户端边界校验供应商响应，避免畸形数据传播到决策解析器。
        try:
            # Chat Completions 返回 choices 列表，这里只取第一条候选回复的正文。
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("LLM 返回结构不符合 OpenAI-compatible 格式") from exc
        if not isinstance(content, str) or not content.strip():
            raise LLMError("LLM 返回了空内容")
        return content
