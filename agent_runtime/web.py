# 模块职责：连接浏览器与 Agent，提供 HTTP API、静态文件服务和启动配置。
# 请求路径：浏览器 POST 消息 → handle_post → runtime.run → 返回答案、会话和日志。
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from .context import ContextManager
from .llm import OpenAICompatibleClient
from .runtime import AgentRuntime
from .session import SessionNotFoundError, SessionStore


class AgentWebApplication:
    """将 AgentRuntime 暴露为轻量 HTTP API，并负责静态页面托管。"""

    def __init__(
        self,
        runtime: AgentRuntime,
        sessions: SessionStore,
        static_root: str | Path,
    ) -> None:
        self.runtime = runtime
        self.sessions = sessions
        self.static_root = Path(static_root).resolve()

    def handler_class(self) -> type[BaseHTTPRequestHandler]:
        # 闭包绑定 application，避免在每个请求处理器中重新构造运行时依赖。
        application = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "MinimalAgentWeb/1.0"

            def do_GET(self) -> None:  # noqa: N802
                # do_GET/do_POST 是标准库要求的方法名，不能随意改成其他名称。
                application.handle_get(self)

            def do_POST(self) -> None:  # noqa: N802
                application.handle_post(self)

            def log_message(self, format: str, *args: Any) -> None:
                # 访问日志默认关闭；它记录 HTTP 请求，与 Agent 的 Trace 不是同一类日志。
                if os.getenv("WEB_ACCESS_LOG") == "1":
                    super().log_message(format, *args)

        # 返回类而非实例；HTTP Server 会为连接创建相应的请求处理器。
        return Handler

    def handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        """处理只读 API；未命中的路径交由静态资源处理。"""

        path = unquote(urlparse(handler.path).path)
        # 去掉查询参数并解码路径后按路由分支处理；health 只检查服务可响应，不调用 LLM。
        if path == "/api/health":
            return self._json(handler, {"ok": True, "provider": "DeepSeek"})
        if path == "/api/meta":
            return self._json(
                handler,
                {
                    "provider": "DeepSeek",
                    "model": getattr(self.runtime.llm, "model", "deepseek-v4-flash"),
                    "tools": self.runtime.registry.schemas(),
                    "max_steps": self.runtime.max_steps,
                },
            )
        if path == "/api/sessions":
            return self._json(
                handler, {"sessions": [self._session_card(item) for item in self.sessions.list()]}
            )
        match = re.fullmatch(r"/api/sessions/([A-Za-z0-9_-]+)", path)
        # 正则中的括号捕获 session_id，match.group(1) 取出该值。
        if match:
            try:
                session = self.sessions.load(match.group(1))
            except SessionNotFoundError:
                return self._error(handler, HTTPStatus.NOT_FOUND, "Session 不存在")
            return self._json(handler, self._session_detail(session))
        match = re.fullmatch(r"/api/sessions/([A-Za-z0-9_-]+)/traces", path)
        if match:
            try:
                self.sessions.load(match.group(1))
            except SessionNotFoundError:
                return self._error(handler, HTTPStatus.NOT_FOUND, "Session 不存在")
            return self._json(
                handler,
                {"traces": self.runtime.traces.read_last(match.group(1), limit=80)},
            )
        return self._static(handler, path)

    def handle_post(self, handler: BaseHTTPRequestHandler) -> None:
        """处理会话创建与发送消息接口。"""

        path = unquote(urlparse(handler.path).path)
        if path == "/api/sessions":
            session = self.sessions.create()
            return self._json(handler, self._session_detail(session), HTTPStatus.CREATED)
        match = re.fullmatch(r"/api/sessions/([A-Za-z0-9_-]+)/messages", path)
        if match:
            try:
                payload = self._read_json(handler)
                message = payload.get("message")
                if not isinstance(message, str) or not message.strip():
                    return self._error(handler, HTTPStatus.BAD_REQUEST, "message 必须是非空字符串")
                # 同步等待这一轮 Agent 结束，再一次性返回 JSON；这里没有流式推送。
                result = self.runtime.run(match.group(1), message)
                # 重新加载已持久化状态，让网页得到这一轮执行后的消息和待办。
                session = self.sessions.load(match.group(1))
            except SessionNotFoundError:
                return self._error(handler, HTTPStatus.NOT_FOUND, "Session 不存在")
            except ValueError as exc:
                return self._error(handler, HTTPStatus.BAD_REQUEST, str(exc))
            except Exception as exc:
                # HTTP 边界不返回内部异常详情，避免向客户端泄露实现和敏感配置。
                return self._error(
                    handler,
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    f"请求执行失败: {type(exc).__name__}",
                )
            return self._json(
                handler,
                {
                    "result": {
                        "answer": result.answer,
                        "steps": result.steps,
                        "error": result.error,
                    },
                    "session": self._session_detail(session),
                    "traces": self.runtime.traces.read_last(session.id, limit=80),
                },
            )
        return self._error(handler, HTTPStatus.NOT_FOUND, "接口不存在")

    @staticmethod
    def _session_card(session) -> dict[str, Any]:
        # 侧栏只需要简短信息；从当前保留消息中的首条用户输入生成标题。
        # next(..., "") 在没有用户消息时返回空字符串，最终显示“新对话”。
        first_user = next((item.content for item in session.messages if item.role == "user"), "")
        return {
            "id": session.id,
            "title": first_user[:28] + ("…" if len(first_user) > 28 else "") or "新对话",
            "message_count": len(session.messages),
            "todo_count": len([item for item in session.todos if not item.done]),
            "updated_at": session.updated_at,
        }

    @classmethod
    def _session_detail(cls, session) -> dict[str, Any]:
        # ** 合并侧栏字段，再补充聊天区和记忆面板需要的完整数据。
        return {
            **cls._session_card(session),
            "summary": session.summary,
            "messages": [item.to_dict() for item in session.messages],
            "todos": [item.to_dict() for item in session.todos],
            "created_at": session.created_at,
        }

    @staticmethod
    def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
        """读取有限大小的 UTF-8 JSON object 请求体。"""

        try:
            length = int(handler.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Content-Length 非法") from exc
        if length <= 0 or length > 1_000_000:
            raise ValueError("请求体为空或过大")
        try:
            # rfile 是请求输入流；按声明长度读字节，再解码文本并解析 JSON。
            value = json.loads(handler.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("请求体必须是合法 UTF-8 JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("请求体必须是 JSON object")
        return value

    def _static(self, handler: BaseHTTPRequestHandler, request_path: str) -> None:
        # 根路径显示首页；其他路径相对于 web 静态目录查找 HTML、CSS、JS 等文件。
        relative = "index.html" if request_path in ("", "/") else request_path.lstrip("/")
        candidate = (self.static_root / relative).resolve()
        # resolve 后再次检查父目录，阻止通过编码或 .. 读取静态目录外的文件。
        if self.static_root not in candidate.parents and candidate != self.static_root:
            return self._error(handler, HTTPStatus.FORBIDDEN, "禁止访问")
        if not candidate.is_file():
            return self._error(handler, HTTPStatus.NOT_FOUND, "页面不存在")
        content = candidate.read_bytes()
        mime = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        handler.send_response(HTTPStatus.OK)
        handler.send_header("Content-Type", f"{mime}; charset=utf-8" if mime.startswith("text/") else mime)
        handler.send_header("Content-Length", str(len(content)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(content)

    @staticmethod
    def _json(
        handler: BaseHTTPRequestHandler,
        payload: dict[str, Any],
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        # 响应顺序：状态码 → 响应头 → end_headers → 正文字节。
        # ensure_ascii=False 保留中文；Content-Length 使用编码后的字节数。
        content = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(content)))
        handler.send_header("Cache-Control", "no-store")
        handler.end_headers()
        handler.wfile.write(content)

    @classmethod
    def _error(
        cls, handler: BaseHTTPRequestHandler, status: HTTPStatus, message: str
    ) -> None:
        # 错误也统一返回 JSON，浏览器可用相同方式读取 error 字段。
        cls._json(handler, {"error": message}, status)


def build_server(
    runtime: AgentRuntime,
    sessions: SessionStore,
    static_root: str | Path,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> ThreadingHTTPServer:
    # 多线程服务器允许不同请求并行；同一 Session 的串行规则由 SessionStore 的锁保证。
    app = AgentWebApplication(runtime, sessions, static_root)
    return ThreadingHTTPServer((host, port), app.handler_class())


def build_parser() -> argparse.ArgumentParser:
    # 命令行选项示例：python web.py --port 8080 --data-dir data。
    parser = argparse.ArgumentParser(description="最小可用 Agent（Web）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data-dir", default="data")
    return parser


def main() -> None:
    # 启动装配：解析参数 → 创建模型客户端 → 创建存储和 Runtime → 启动 HTTP 服务。
    args = build_parser().parse_args()
    try:
        llm = OpenAICompatibleClient.from_env()
    except ValueError as exc:
        raise SystemExit(f"配置错误：{exc}") from exc
    data_dir = Path(args.data_dir)
    sessions = SessionStore(data_dir / "sessions")
    runtime = AgentRuntime(
        llm=llm,
        sessions=sessions,
        max_steps=int(os.getenv("AGENT_MAX_STEPS", "8")),
        context=ContextManager(max_chars=int(os.getenv("AGENT_CONTEXT_CHARS", "24000"))),
    )
    server = build_server(
        # __file__ 定位当前文件，向上两级到项目根，再找到前端 web 文件夹。
        runtime, sessions, Path(__file__).parent.parent / "web", args.host, args.port
    )
    print(f"Agent Web 已启动：http://{args.host}:{args.port}")
    try:
        # 持续监听请求，直到 Ctrl+C 触发 KeyboardInterrupt。
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。")
    finally:
        # 无论正常退出还是异常结束，都释放服务器监听资源。
        server.server_close()
