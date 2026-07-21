from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Message:
    role: Literal["user", "assistant", "tool"]
    content: str
    name: str | None = None
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Message":
        return cls(**value)


@dataclass
class TodoItem:
    id: int
    text: str
    done: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Session:
    id: str
    messages: list[Message] = field(default_factory=list)
    summary: str = ""
    todos: list[TodoItem] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "messages": [item.to_dict() for item in self.messages],
            "summary": self.summary,
            "todos": [item.to_dict() for item in self.todos],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Session":
        return cls(
            id=value["id"],
            messages=[Message.from_dict(item) for item in value.get("messages", [])],
            summary=value.get("summary", ""),
            todos=[TodoItem(**item) for item in value.get("todos", [])],
            created_at=value.get("created_at", utc_now()),
            updated_at=value.get("updated_at", utc_now()),
        )


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentDecision:
    type: Literal["tool_call", "final"]
    reasoning_summary: str = ""
    name: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    answer: str | None = None

