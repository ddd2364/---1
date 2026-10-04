# 模块职责：按会话 ID 创建、读取和保存状态，并协调同一会话的并发请求。
# 一份 Session 对应一个 JSON 文件；Trace 由另一个模块独立保存。
from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from threading import Lock

from .models import Session, utc_now


class SessionNotFoundError(KeyError):
    pass


class SessionStore:
    """每个会话独立存储为一个文件，避免不同聊天窗口共享可变状态。"""

    _VALID_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")

    def __init__(self, root: str | Path = "data/sessions") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        # 每个会话一个锁；_locks_guard 仅保护“查找/创建锁”这份共享字典。
        self._locks: dict[str, Lock] = {}
        self._locks_guard = Lock()

    @contextmanager
    def turn(self, session_id: str):
        """同一窗口串行处理整轮请求；不同窗口可独立运行。仅保护本进程。"""
        self._path(session_id)
        with self._locks_guard:
            # setdefault：已有该会话的锁就复用，否则加入新锁。
            lock = self._locks.setdefault(session_id, Lock())
        with lock:
            # yield 前获取锁，yield 时执行调用方的 with 代码块，退出后释放锁。
            # 字典锁已释放，因此等待此会话不会同时堵住其他会话的锁查找。
            yield

    def create(self) -> Session:
        # UUID 不依赖会话标题，因此两个同名聊天仍有独立的状态文件。
        session = Session(id=str(uuid.uuid4()))
        self.save(session)
        return session

    def _path(self, session_id: str) -> Path:
        # 白名单限制同时保证文件名稳定，并阻止 ../ 等路径穿越输入。
        if not self._VALID_ID.fullmatch(session_id):
            raise ValueError("非法 session_id")
        return self.root / f"{session_id}.json"

    def load(self, session_id: str) -> Session:
        # 每次加载都会重建对象；调用方修改后必须 save 才能保留到磁盘。
        path = self._path(session_id)
        if not path.exists():
            raise SessionNotFoundError(session_id)
        try:
            return Session.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError, KeyError) as exc:
            raise RuntimeError(f"Session 文件损坏: {session_id}") from exc

    def save(self, session: Session) -> None:
        """以“临时文件 + 原子替换”的方式保存会话。"""

        session.updated_at = utc_now()
        path = self._path(session.id)
        payload = json.dumps(session.to_dict(), ensure_ascii=False, indent=2)
        # 临时文件与目标文件位于同一目录，os.replace 才能可靠地原子替换。
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{session.id}.", suffix=".tmp", dir=self.root
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                # os.fdopen 将临时文件描述符包装成可写文本流，with 负责关闭它。
                stream.write(payload)
                stream.flush()
                # 先将缓冲内容同步到磁盘，再替换正式文件，降低进程崩溃时的数据损坏风险。
                os.fsync(stream.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def list(self) -> list[Session]:
        """列出可正常加载的会话，损坏文件不会影响其他会话展示。"""

        sessions: list[Session] = []
        for path in self.root.glob("*.json"):
            try:
                sessions.append(self.load(path.stem))
            except RuntimeError:
                continue
        # 最新更新的会话排在最前，供网页侧栏展示。
        return sorted(sessions, key=lambda item: item.updated_at, reverse=True)
