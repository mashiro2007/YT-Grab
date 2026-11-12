"""Local HTTP server and JSON API for the YouTube downloader."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import traceback
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from ytdl_core import (
    AUDIO_FORMATS,
    AUDIO_QUALITIES,
    DOWNLOAD_DIR,
    THUMB_QUALITIES,
    WEB_DIR,
    DownloadManager,
    UserError,
    cookies_file,
    extract_info,
    fetch_thumbnail,
    ffmpeg_health,
    parse_youtube_url,
    ytdlp_health,
)

APP_VERSION = "1.0.0"
STATIC_FILES = {
    "/static/style.css": ("style.css", "text/css; charset=utf-8"),
    "/static/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/static/favicon.svg": ("favicon.svg", "image/svg+xml"),
    "/favicon.ico": ("favicon.svg", "image/svg+xml"),
}
JOB_PATH_RE = re.compile(r"^/api/jobs/([a-f0-9]{6,32})(?:/(cancel))?$")


def _is_local_host(host: str) -> bool:
    host = (host or "").split(":")[0].strip("[]").lower()
    return host in {"127.0.0.1", "localhost", "::1"}


class AppServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], manager: DownloadManager):
        self.manager = manager
        super().__init__(address, AppHandler)


class AppHandler(BaseHTTPRequestHandler):
    server: AppServer
    server_version = "YTGrab/1.0"

    # -- HTTP verbs ---------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        if not self._check_local_request():
            return
        try:
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path
            if path == "/":
                self._send_static("index.html", "text/html; charset=utf-8")
                return
            if path in STATIC_FILES:
                filename, content_type = STATIC_FILES[path]
                self._send_static(filename, content_type)
                return
            if path == "/api/health":
                self._send_json(HTTPStatus.OK, self._health())
                return
            if path == "/api/jobs":
                self._send_json(HTTPStatus.OK, {"jobs": self.server.manager.list()})
                return
            match = JOB_PATH_RE.match(path)
            if match and not match.group(2):
                job = self.server.manager.get(match.group(1))
                if not job:
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "下载任务不存在。"})
                    return
                self._send_json(HTTPStatus.OK, {"job": job.snapshot()})
                return
            if path.startswith("/api/thumbnail/"):
                video_id = path[len("/api/thumbnail/"):]
                quality = (urllib.parse.parse_qs(parsed.query).get("q") or ["hq"])[0]
                self._serve_thumbnail(video_id, quality)
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "页面不存在。"})
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:  # noqa: BLE001
            self._unexpected()

    def do_POST(self) -> None:  # noqa: N802
        if not self._check_local_request():
            return
        try:
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path
            if path == "/api/info":
                body = self._read_json()
                url = str(body.get("url") or "")
                info = extract_info(url)
                self._send_json(HTTPStatus.OK, info)
                return
            if path == "/api/download":
                self._start_download(self._read_json())
                return
            if path == "/api/open-folder":
                self._open_folder(self._read_json())
                return
            match = JOB_PATH_RE.match(path)
            if match and match.group(2) == "cancel":
                ok = self.server.manager.cancel(match.group(1))
                self._send_json(HTTPStatus.OK if ok else HTTPStatus.NOT_FOUND, {"ok": ok})
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在。"})
        except UserError as exc:
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": exc.message, "hint": exc.hint, "detail": exc.detail[:3000]},
            )
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:  # noqa: BLE001
            self._unexpected()

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    # -- API helpers --------------------------------------------------------
    def _health(self) -> dict[str, Any]:
        return {
            "app": "YT Grab",
            "version": APP_VERSION,
            "ytdlp": ytdlp_health(),
            "ffmpeg": ffmpeg_health(),
            "cookies": cookies_file() is not None,
            "download_dir": str(DOWNLOAD_DIR),
        }

    def _start_download(self, body: dict[str, Any]) -> None:
        video_id, canonical = parse_youtube_url(str(body.get("url") or ""))
        kind = str(body.get("kind") or "")
        if kind not in {"video", "audio", "thumbnail", "muted"}:
            raise UserError("未知的下载类型。")
        if kind == "video" and bool(body.get("muted")):
            kind = "muted"

        options: dict[str, Any] = {}
        if kind in {"video", "muted"}:
            raw_height = body.get("height", "best")
            if raw_height == "best":
                height: int | str = "best"
            else:
                try:
                    height = int(raw_height)
                except (TypeError, ValueError) as exc:
                    raise UserError("分辨率参数无效。") from exc
                if height < 144 or height > 4320:
                    raise UserError("分辨率超出支持范围。")
            options["height"] = height
            options["compat"] = bool(body.get("compat", True))
            options["muted"] = kind == "muted"

        if kind == "audio":
            audio_format = str(body.get("audio_format") or "mp3").lower()
            if audio_format not in AUDIO_FORMATS:
                raise UserError("音频格式无效。")
            options["audio_format"] = audio_format
            if audio_format not in {"best", "wav"}:
                try:
                    quality = int(body.get("audio_quality") or 192)
                except (TypeError, ValueError) as exc:
                    raise UserError("音频码率无效。") from exc
                if quality not in AUDIO_QUALITIES:
                    quality = 192
                options["audio_quality"] = quality

        if kind == "thumbnail":
            quality = str(body.get("thumb_quality") or "maxres")
            if quality not in THUMB_QUALITIES:
                raise UserError("封面尺寸无效。")
            options["thumb_quality"] = quality

        title = str(body.get("title") or "").strip()
        title = re.sub(r"[\x00-\x1f]", "", title)[:240]
        if not title:
            title = f"YouTube {video_id}"
        job = self.server.manager.start(kind, video_id, canonical, title, options)
        self._send_json(HTTPStatus.ACCEPTED, {"job": job})

    def _open_folder(self, body: dict[str, Any]) -> None:
        job_id = str(body.get("job_id") or "")
        target: Path = DOWNLOAD_DIR
        job = self.server.manager.get(job_id) if job_id else None
        if job and job.files:
            candidate = Path(job.files[0].get("path", "")).resolve()
            try:
                if candidate.is_file() and candidate.is_relative_to(DOWNLOAD_DIR.resolve()):
                    target = candidate
            except OSError:
                pass
        if target.is_file():
            self._reveal_file(target)
        else:
            self._open_directory(DOWNLOAD_DIR)
        self._send_json(HTTPStatus.OK, {"ok": True})

    @staticmethod
    def _open_directory(path: Path) -> None:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    @staticmethod
    def _reveal_file(path: Path) -> None:
        if os.name == "nt":
            subprocess.Popen(["explorer.exe", "/select,", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])

    def _serve_thumbnail(self, video_id: str, quality: str) -> None:
        try:
            data, _actual, content_type = fetch_thumbnail(video_id, quality)
        except UserError:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "封面不可用。"})
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    # -- HTTP plumbing ------------------------------------------------------
    def _check_local_request(self) -> bool:
        if not _is_local_host(self.headers.get("Host", "")):
            self._send_json(HTTPStatus.FORBIDDEN, {"error": "仅允许本机访问。"})
            return False
        origin = self.headers.get("Origin", "")
        if origin:
            try:
                origin_host = urllib.parse.urlsplit(origin).hostname or ""
            except ValueError:
                origin_host = ""
            if not _is_local_host(origin_host):
                self._send_json(HTTPStatus.FORBIDDEN, {"error": "跨站请求被拒绝。"})
                return False
        return True

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except ValueError as exc:
            raise UserError("请求内容无效。") from exc
        if length > 65536:
            raise UserError("请求内容过大。")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise UserError("请求内容不是有效的 JSON。") from exc
        if not isinstance(data, dict):
            raise UserError("请求内容格式不正确。")
        return data

    def _send_static(self, filename: str, content_type: str) -> None:
        path = WEB_DIR / filename
        try:
            data = path.read_bytes()
        except OSError:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "页面文件缺失。"})
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; base-uri 'none'; "
            "form-action 'self'; frame-ancestors 'none'",
        )
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _send_json(self, status: int | HTTPStatus, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _unexpected(self) -> None:
        traceback.print_exc()
        try:
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "服务器内部错误。", "hint": "请查看运行窗口中的错误信息。"},
            )
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, fmt: str, *args: Any) -> None:
        # Polling /api/jobs would otherwise flood the console.
        if "/api/jobs" in self.path:
            return
        super().log_message(fmt, *args)


def create_server(manager: DownloadManager, preferred_port: int = 8765) -> tuple[AppServer, str]:
    last_error: Exception | None = None
    for port in range(preferred_port, preferred_port + 20):
        try:
            server = AppServer(("127.0.0.1", port), manager)
            return server, f"http://127.0.0.1:{port}"
        except OSError as exc:
            last_error = exc
            continue
    raise RuntimeError(f"无法找到可用端口：{last_error}")
