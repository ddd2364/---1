# 模块职责：定义各模块共同使用的数据结构，不负责调用模型或执行工具。
# dataclass 自动生成 __init__ 等方法；类型注解帮助阅读，但不会自动校验传入数据。
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal


def utc_now() -> str:
    # 使用带时区的 UTC 时间字符串，方便保存成 JSON 和按时间排序。
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Message:
    # role 区分用户输入、模型输出和工具结果；name 用于标记关联的工具。
    role: Literal["user", "assistant", "tool"]
    content: str
    name: str | None = None
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        # asdict 将 dataclass 转为普通字典，交给 json.dumps 序列化。
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Message":
        # ** 将字典展开为命名参数，相当于 Message(role=..., content=...)。
        return cls(**value)


@dataclass
class TodoItem:
    # id 在当前会话中标识待办；done=True 表示已经完成。
    id: int
    text: str
    done: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Session:
    # summary 保存旧对话摘要，messages 保存当前保留的消息，todos 保存结构化状态。
    id: str
    # default_factory=list 为每个实例新建列表，避免多个会话共享同一个列表。
    messages: list[Message] = field(default_factory=list)
    summary: str = ""
    todos: list[TodoItem] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        # 嵌套对象也要转成字典列表，才能完整写入会话 JSON 文件。
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
        # 从文件读到的是字典和列表；这里重建 Message、TodoItem 和 Session 对象。
        # get(..., 默认值) 允许缺少可选字段，但 id 是恢复会话必需的字段。
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
    # 工具统一返回这三项；失败也是一种可回填给模型的结果。
    ok: bool
    data: Any = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentDecision:
    # tool_call 使用 name/arguments；final 使用 answer。
    # 具体字段是否合法由 parser.py 检查，Literal 本身不做运行时校验。
    type: Literal["tool_call", "final"]
    reasoning_summary: str = ""
    name: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    answer: str | None = None
