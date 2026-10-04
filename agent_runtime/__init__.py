"""A small, framework-free Agent runtime."""

# 包的公共入口：调用方可直接 from agent_runtime import AgentRuntime。
# 实际实现仍在对应模块中，这里只统一导出常用对象。
from .runtime import AgentRuntime, RunResult
from .session import SessionStore

# __all__ 声明星号导入时导出的名字，不会阻止显式导入其他模块。
__all__ = ["AgentRuntime", "RunResult", "SessionStore"]
