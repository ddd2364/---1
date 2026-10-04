# 模块职责：记录执行过程，供网页展示和排查问题；这些日志不会自动回填模型。
# Session JSON 保存当前状态，Trace JSONL 按时间追加发生过的事件。
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import utc_now


class TraceLogger:
    """以 JSON Lines 追加记录运行事件，便于逐步排障和审计。"""

    def __init__(self, root: str | Path = "data/traces") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def log(self, session_id: str, event: str, **details: Any) -> None:
        # **details 收集任意命名字段，如 run_id、step、tool、arguments、result。
        # 一行一个完整 JSON 对象，单条异常写入不会破坏此前的追踪记录。
        record = {"at": utc_now(), "event": event, **details}
        # a 表示追加模式；每个会话单独一个文件，一行一个完整 JSON 对象。
        with (self.root / f"{session_id}.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def read_last(self, session_id: str, limit: int = 30) -> list[dict[str, Any]]:
        """读取最近若干事件，避免 Web 接口一次返回完整追踪文件。"""

        path = self.root / f"{session_id}.jsonl"
        if not path.exists():
            return []
        # 当前实现先读整个文件，再截取末尾 limit 行；限制的是返回量，不是读取量。
        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
        return [json.loads(line) for line in lines]
