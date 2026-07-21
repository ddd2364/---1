from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from pathlib import Path

from .models import Session, utc_now


class SessionNotFoundError(KeyError):
    pass


class SessionStore:
    """File-per-session persistence keeps different chat windows isolated."""

    _VALID_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")

    def __init__(self, root: str | Path = "data/sessions") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def create(self) -> Session:
        session = Session(id=str(uuid.uuid4()))
        self.save(session)
        return session

    def _path(self, session_id: str) -> Path:
        if not self._VALID_ID.fullmatch(session_id):
            raise ValueError("非法 session_id")
        return self.root / f"{session_id}.json"

    def load(self, session_id: str) -> Session:
        path = self._path(session_id)
        if not path.exists():
            raise SessionNotFoundError(session_id)
        try:
            return Session.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError, KeyError) as exc:
            raise RuntimeError(f"Session 文件损坏: {session_id}") from exc

    def save(self, session: Session) -> None:
        session.updated_at = utc_now()
        path = self._path(session.id)
        payload = json.dumps(session.to_dict(), ensure_ascii=False, indent=2)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{session.id}.", suffix=".tmp", dir=self.root
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def list(self) -> list[Session]:
        sessions: list[Session] = []
        for path in self.root.glob("*.json"):
            try:
                sessions.append(self.load(path.stem))
            except RuntimeError:
                continue
        return sorted(sessions, key=lambda item: item.updated_at, reverse=True)

