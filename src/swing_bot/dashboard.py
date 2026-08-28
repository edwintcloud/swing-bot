from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
from collections.abc import Sequence
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from swing_bot.dashboard_bridge import dashboard_payload, enqueue_command


def resolve_static_asset(root: Path, request_path: str) -> Path | None:
    relative = unquote(urlparse(request_path).path).lstrip("/") or "index.html"
    candidate = (root / relative).resolve()
    resolved_root = root.resolve()
    if not candidate.is_relative_to(resolved_root) or not candidate.is_file():
        return None
    return candidate


class DashboardHandler(BaseHTTPRequestHandler):
    runtime_dir = Path("runtime")
    static_dir = Path("ui/dist")
    username = "admin"
    password = ""

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/healthz":
            self._json({"status": "ok"})
            return
        if not self._authorized():
            return
        if path == "/api/state":
            self._json(dashboard_payload(self.runtime_dir))
            return
        asset = resolve_static_asset(self.static_dir, self.path)
        if asset is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
        self._send(
            asset.read_bytes(),
            f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type,
            cache_control=(
                "no-store" if asset.name == "index.html" else "public, max-age=31536000, immutable"
            ),
        )

    def do_POST(self) -> None:
        if not self._authorized() or not self._same_origin():
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            self._json({"error": "Invalid JSON body"}, HTTPStatus.BAD_REQUEST)
            return
        if self.path == "/api/pause" and isinstance(payload.get("paused"), bool):
            command_id = enqueue_command(
                self.runtime_dir, "set_paused", {"paused": payload["paused"]}
            )
        elif self.path == "/api/flatten" and (
            payload.get("instrument_id") is None
            or (
                isinstance(payload.get("instrument_id"), str)
                and bool(payload["instrument_id"])
            )
        ):
            command_payload = (
                {"instrument_id": payload["instrument_id"]}
                if payload.get("instrument_id") is not None
                else {}
            )
            command_id = enqueue_command(self.runtime_dir, "flatten", command_payload)
        else:
            self._json({"error": "Unknown command"}, HTTPStatus.BAD_REQUEST)
            return
        self._json({"accepted": True, "command_id": command_id}, HTTPStatus.ACCEPTED)

    def _authorized(self) -> bool:
        if not self.password:
            return True
        expected = "Basic " + base64.b64encode(
            f"{self.username}:{self.password}".encode()
        ).decode()
        if self.headers.get("Authorization") == expected:
            return True
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="Swing Control"')
        self.end_headers()
        return False

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin or urlparse(origin).netloc == self.headers.get("Host"):
            return True
        self._json({"error": "Cross-origin commands are forbidden"}, HTTPStatus.FORBIDDEN)
        return False

    def _json(self, value: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        self._send(
            json.dumps(value, separators=(",", ":")).encode(),
            "application/json",
            status,
        )

    def _send(
        self,
        content: bytes,
        content_type: str,
        status: HTTPStatus = HTTPStatus.OK,
        cache_control: str = "no-store",
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", cache_control)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "font-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
        )
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args: object) -> None:
        return


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="swing-bot dashboard")
    parser.add_argument("--runtime-dir", default=os.getenv("DASHBOARD_RUNTIME_PATH", "runtime"))
    parser.add_argument(
        "--static-dir", default=os.getenv("DASHBOARD_STATIC_PATH", "ui/dist")
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)
    DashboardHandler.runtime_dir = Path(args.runtime_dir)
    DashboardHandler.static_dir = Path(args.static_dir)
    DashboardHandler.username = os.getenv("DASHBOARD_USERNAME", "admin")
    DashboardHandler.password = os.getenv("DASHBOARD_PASSWORD", "")
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
