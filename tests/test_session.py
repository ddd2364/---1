if __name__ == "__main__":
    import _bootstrap

import json

import pytest

from agent_runtime.models import Message
from agent_runtime.session import SessionNotFoundError, SessionStore


def test_sessions_are_persistent_and_isolated(tmp_path):
    store = SessionStore(tmp_path / "sessions")
    first, second = store.create(), store.create()
    first.messages.append(Message(role="user", content="窗口一"))
    store.save(first)

    reopened = SessionStore(tmp_path / "sessions")
    assert reopened.load(first.id).messages[0].content == "窗口一"
    assert reopened.load(second.id).messages == []
    assert len(reopened.list()) == 2


def test_invalid_or_missing_session(tmp_path):
    store = SessionStore(tmp_path)
    with pytest.raises(ValueError):
        store.load("../escape")
    with pytest.raises(SessionNotFoundError):
        store.load("missing")


def test_corrupt_session_is_reported(tmp_path):
    store = SessionStore(tmp_path)
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    with pytest.raises(RuntimeError):
        store.load("broken")


if __name__ == "__main__":
    raise SystemExit(_bootstrap.run(__file__))
