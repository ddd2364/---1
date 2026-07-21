from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import utc_now


class TraceLogger:
    def __init__(self, root: str | Path = "data/traces") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def log(self, session_id: str, event: str, **details: Any) -> None:
        record = {"at": utc_now(), "event": event, **details}
        with (self.root / f"{session_id}.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    def read_last(self, session_id: str, limit: int = 30) -> list[dict[str, Any]]:
        path = self.root / f"{session_id}.jsonl"
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
        return [json.loads(line) for line in lines]
