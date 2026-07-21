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
        application = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "MinimalAgentWeb/1.0"

            def do_GET(self) -> None:  # noqa: N802
                application.handle_get(self)

            def do_POST(self) -> None:  # noqa: N802
                application.handle_post(self)

            def log_message(self, format: str, *args: Any) -> None:
                if os.getenv("WEB_ACCESS_LOG") == "1":
                    super().log_message(format, *args)

        return Handler

    def handle_get(self, handler: BaseHTTPRequestHandler) -> None:
        path = unquote(urlparse(handler.path).path)
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
                result = self.runtime.run(match.group(1), message)
                session = self.sessions.load(match.group(1))
            except SessionNotFoundError:
                return self._error(handler, HTTPStatus.NOT_FOUND, "Session 不存在")
            except ValueError as exc:
                return self._error(handler, HTTPStatus.BAD_REQUEST, str(exc))
            except Exception as exc:
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
        return {
            **cls._session_card(session),
            "summary": session.summary,
            "messages": [item.to_dict() for item in session.messages],
            "todos": [item.to_dict() for item in session.todos],
            "created_at": session.created_at,
        }

    @staticmethod
    def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
        try:
            length = int(handler.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Content-Length 非法") from exc
        if length <= 0 or length > 1_000_000:
            raise ValueError("请求体为空或过大")
        try:
            value = json.loads(handler.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("请求体必须是合法 UTF-8 JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("请求体必须是 JSON object")
        return value

    def _static(self, handler: BaseHTTPRequestHandler, request_path: str) -> None:
        relative = "index.html" if request_path in ("", "/") else request_path.lstrip("/")
        candidate = (self.static_root / relative).resolve()
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
        cls._json(handler, {"error": message}, status)


def build_server(
    runtime: AgentRuntime,
    sessions: SessionStore,
    static_root: str | Path,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> ThreadingHTTPServer:
    app = AgentWebApplication(runtime, sessions, static_root)
    return ThreadingHTTPServer((host, port), app.handler_class())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="最小可用 Agent（Web）")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--data-dir", default="data")
    return parser


def main() -> None:
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
        runtime, sessions, Path(__file__).parent.parent / "web", args.host, args.port
    )
    print(f"Agent Web 已启动：http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止。")
    finally:
        server.server_close()
