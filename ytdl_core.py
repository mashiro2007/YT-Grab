"""Core download engine for the local YouTube downloader.

The app deliberately uses a vendored yt-dlp Python package instead of a
PyInstaller one-file executable: it starts faster, avoids temp-directory
extraction, and is easy to update with ``update-ytdlp.bat``.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
VENDOR_DIR = BASE_DIR / "vendor"
DOWNLOAD_DIR = BASE_DIR / "downloads"
WORK_DIR = BASE_DIR / "work"
WEB_DIR = BASE_DIR / "web"

if str(VENDOR_DIR) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIR))

try:
    import yt_dlp  # noqa: F401  (also validates the vendored install)
except ImportError as exc:  # pragma: no cover - startup guard
    raise SystemExit(
        "缺少 vendor/yt_dlp。请运行 update-ytdlp.bat，"
        "或执行: python -m pip install --target vendor yt-dlp"
    ) from exc

try:
    from yt_dlp.version import __version__ as YTDLP_VERSION
except Exception:  # pragma: no cover
    YTDLP_VERSION = "unknown"

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
PROGRESS_MARKER = "@@YTDL_PROGRESS@@"
PROGRESS_TEMPLATE = (
    "download:" + PROGRESS_MARKER
    + "%(progress.downloaded_bytes)s|%(progress.total_bytes)s|"
      "%(progress.total_bytes_estimate)s|%(progress.speed)s|"
      "%(progress.eta)s|%(progress._percent_str)s"
)

THUMB_FILE_TO_QUALITY = {
    "maxresdefault.jpg": "maxres",
    "sddefault.jpg": "sd",
    "hqdefault.jpg": "hq",
    "mqdefault.jpg": "mq",
}

THUMB_QUALITIES: dict[str, dict[str, Any]] = {
    "maxres": {
        "label": "最高清",
        "detail": "1280×720",
        "files": ["maxresdefault.jpg", "sddefault.jpg", "hqdefault.jpg", "mqdefault.jpg"],
    },
    "sd": {
        "label": "高清",
        "detail": "640×480",
        "files": ["sddefault.jpg", "hqdefault.jpg", "mqdefault.jpg"],
    },
    "hq": {
        "label": "标准",
        "detail": "480×360",
        "files": ["hqdefault.jpg", "mqdefault.jpg"],
    },
    "mq": {
        "label": "小图",
        "detail": "320×180",
        "files": ["mqdefault.jpg", "hqdefault.jpg"],
    },
}

AUDIO_FORMATS = {"mp3", "m4a", "opus", "wav", "best"}
AUDIO_QUALITIES = {320, 256, 192, 160, 128, 96}
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


class UserError(Exception):
    """An error that is safe and useful to show in the UI."""

    def __init__(self, message: str, hint: str = "", detail: str = ""):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.detail = detail


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def ensure_dirs() -> None:
    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    WEB_DIR.mkdir(parents=True, exist_ok=True)
    # Clean stale staging directories from previous crashes (older than 24 h).
    cutoff = time.time() - 24 * 3600
    try:
        for child in WORK_DIR.iterdir():
            if child.is_dir() and child.stat().st_mtime < cutoff:
                shutil.rmtree(child, ignore_errors=True)
    except OSError:
        pass


def subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    current = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(VENDOR_DIR) + (os.pathsep + current if current else "")
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["NO_COLOR"] = "1"
    return env


def popen_extra() -> dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": CREATE_NO_WINDOW}
    return {"start_new_session": True}


def clean_ansi(text: str) -> str:
    return ANSI_RE.sub("", text or "")


def tail_lines(text: str, limit: int = 30) -> str:
    lines = [line.strip() for line in clean_ansi(text).splitlines() if line.strip()]
    return "\n".join(lines[-limit:])


# ---------------------------------------------------------------------------
# External tool discovery
# ---------------------------------------------------------------------------
_ffmpeg_cache: tuple[Path | None, str] | None = None
_ffmpeg_lock = threading.Lock()


def _candidate_ffmpeg_paths() -> list[Path]:
    candidates: list[Path] = []
    configured = os.environ.get("FFMPEG_LOCATION") or os.environ.get("FFMPEG_PATH")
    if configured:
        path = Path(configured).expanduser()
        candidates.append(path / "ffmpeg.exe" if path.is_dir() else path)

    for name in ("ffmpeg.exe", "ffmpeg"):
        candidates.append(BASE_DIR / "bin" / name)
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))

    local = os.environ.get("LOCALAPPDATA")
    if local:
        packages = Path(local) / "Microsoft" / "WinGet" / "Packages"
        try:
            for match in packages.glob("BtbN.FFmpeg*/**/bin/ffmpeg.exe"):
                candidates.append(match)
        except OSError:
            pass
        try:
            for match in packages.glob("Gyan.FFmpeg*/**/bin/ffmpeg.exe"):
                candidates.append(match)
        except OSError:
            pass

    candidates.extend(
        [
            Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
            Path(r"C:\ProgramData\chocolatey\bin\ffmpeg.exe"),
            Path(r"C:\Program Files\ffmpeg\bin\ffmpeg.exe"),
        ]
    )
    return candidates


def find_ffmpeg() -> tuple[Path | None, str]:
    global _ffmpeg_cache
    with _ffmpeg_lock:
        if _ffmpeg_cache is not None:
            return _ffmpeg_cache
        seen: set[str] = set()
        for path in _candidate_ffmpeg_paths():
            try:
                key = str(path.resolve()).lower()
            except OSError:
                key = str(path).lower()
            if key in seen:
                continue
            seen.add(key)
            if not path.is_file():
                continue
            try:
                proc = subprocess.run(
                    [str(path), "-version"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=8,
                    env=subprocess_env(),
                    **popen_extra(),
                )
                first = (proc.stdout or proc.stderr).splitlines()[0] if (proc.stdout or proc.stderr) else ""
                match = re.search(r"ffmpeg version\s+(\S+)", first, re.I)
                version = match.group(1) if match else "已找到"
                _ffmpeg_cache = (path, version)
                return _ffmpeg_cache
            except (OSError, subprocess.SubprocessError):
                continue
        _ffmpeg_cache = (None, "")
        return _ffmpeg_cache


def ffmpeg_health() -> dict[str, Any]:
    path, version = find_ffmpeg()
    return {"available": path is not None, "path": str(path) if path else "", "version": version}


def ytdlp_health() -> dict[str, Any]:
    return {"version": YTDLP_VERSION, "available": True}


def cookies_file() -> Path | None:
    configured = os.environ.get("YTDLP_COOKIES")
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return path
    default = BASE_DIR / "cookies.txt"
    return default if default.is_file() else None


def cookie_args() -> list[str]:
    args: list[str] = []
    path = cookies_file()
    if path:
        args.extend(["--cookies", str(path)])
    browser = os.environ.get("YTDLP_COOKIES_FROM_BROWSER", "").strip()
    if browser:
        args.extend(["--cookies-from-browser", browser])
    return args


def common_network_args() -> list[str]:
    args = cookie_args()
    proxy = os.environ.get("YTDLP_PROXY", "").strip()
    if proxy:
        args.extend(["--proxy", proxy])
    extractor_args = os.environ.get("YTDLP_EXTRACTOR_ARGS", "").strip()
    if extractor_args:
        args.extend(["--extractor-args", extractor_args])
    return args


def ytdlp_command() -> list[str]:
    # Running the module (rather than importing the API) keeps downloads in a
    # separate process that can be cancelled cleanly, ffmpeg children included.
    return [
        sys.executable,
        "-m",
        "yt_dlp",
        "--ignore-config",
        "--no-colors",
        "--no-warnings",
        "--no-playlist",
        "--socket-timeout",
        "20",
        "--retries",
        "5",
        "--fragment-retries",
        "5",
        "--concurrent-fragments",
        "4",
    ] + common_network_args()


# ---------------------------------------------------------------------------
# URL validation and friendly errors
# ---------------------------------------------------------------------------
def parse_youtube_url(raw: str) -> tuple[str, str]:
    """Return ``(video_id, canonical_watch_url)`` for a single YouTube video."""
    raw = (raw or "").strip()
    if not raw:
        raise UserError("请先粘贴 YouTube 视频链接。")
    if len(raw) > 4096:
        raise UserError("链接过长，请检查后重试。")
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", raw):
        raw = "https://" + raw

    try:
        parsed = urllib.parse.urlsplit(raw)
    except ValueError as exc:
        raise UserError("链接格式不正确。") from exc

    if parsed.scheme not in ("http", "https"):
        raise UserError("只支持 http/https 链接。")
    host = (parsed.hostname or "").lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m."):
        host = host[2:]

    allowed = {
        "youtube.com",
        "music.youtube.com",
        "youtu.be",
        "youtube-nocookie.com",
    }
    if host not in allowed:
        raise UserError(
            "这不是有效的 YouTube 链接。",
            "支持 youtube.com/watch、youtu.be、Shorts、直播回放等单个视频链接。",
        )

    video_id = ""
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
    else:
        path = parsed.path.rstrip("/")
        parts = [part for part in path.split("/") if part]
        if parts[:1] == ["watch"]:
            video_id = (urllib.parse.parse_qs(parsed.query).get("v") or [""])[0]
        elif parts and parts[0] in {"shorts", "live", "embed", "v", "e"} and len(parts) >= 2:
            video_id = parts[1]
        elif path == "/playlist" or (not parts and parsed.query):
            raise UserError(
                "只支持单个视频，暂不支持播放列表或频道链接。",
                "请打开播放列表中的某个视频，复制它的单独链接。",
            )

    video_id = video_id.strip()
    if not VIDEO_ID_RE.match(video_id):
        raise UserError(
            "无法从链接中识别视频 ID。",
            "请确认链接形如 https://www.youtube.com/watch?v=XXXXXXXXXXX 或 https://youtu.be/XXXXXXXXXXX。",
        )
    return video_id, f"https://www.youtube.com/watch?v={video_id}"


def friendly_error(raw: str) -> UserError:
    text = clean_ansi(raw or "")
    lower = text.lower()

    if "sign in to confirm" in lower or "not a bot" in lower or "confirm you're not a bot" in lower:
        return UserError(
            "YouTube 要求确认“你不是机器人”，需要登录凭据。",
            "在浏览器中登录 YouTube，导出 cookies.txt 放到程序目录；"
            "或设置环境变量 YTDLP_COOKIES_FROM_BROWSER=edge（Chrome 用 chrome，Firefox 用 firefox）后重启。",
            tail_lines(text),
        )
    if "private video" in lower or "this video is private" in lower:
        return UserError(
            "这是一个私享视频，当前账号没有访问权限。",
            "使用有权限的账号导出 cookies.txt 后再试。",
            tail_lines(text),
        )
    if "members-only" in lower or "join this channel" in lower:
        return UserError(
            "这是频道会员专属视频。",
            "使用已加入该频道会员的账号 Cookie 后再试。",
            tail_lines(text),
        )
    if "age-restricted" in lower or "confirm your age" in lower or "inappropriate for some users" in lower:
        return UserError(
            "该视频有年龄限制，需要登录账号验证。",
            "导出已登录账号的 cookies.txt 放到程序目录后重试。",
            tail_lines(text),
        )
    if "video unavailable" in lower or "this video is unavailable" in lower:
        return UserError(
            "视频不可用，可能已被删除、设为私享，或在当前地区受限。",
            "检查链接是否有效，必要时配置代理或账号 Cookie。",
            tail_lines(text),
        )
    if "not available in your country" in lower or "geo restricted" in lower or "geo-restricted" in lower:
        return UserError(
            "该视频在当前地区不可用。",
            "可设置 YTDLP_PROXY 环境变量使用代理后重试。",
            tail_lines(text),
        )
    if "requested format is not available" in lower or "no video formats found" in lower:
        return UserError(
            "所选清晰度当前不可用。",
            "重新解析视频，或改选其他分辨率/最佳画质。",
            tail_lines(text),
        )
    if "ffmpeg" in lower and ("not found" in lower or "not installed" in lower or "not found;" in lower):
        return UserError(
            "未找到 FFmpeg，无法合并高清视频或转换音频。",
            "安装 FFmpeg 并加入 PATH，或把 ffmpeg.exe 放到程序目录的 bin 文件夹。",
            tail_lines(text),
        )
    if "http error 403" in lower or "forbidden" in lower:
        return UserError(
            "YouTube 拒绝了媒体请求（HTTP 403）。",
            "稍后重试；若持续失败，请更新 yt-dlp 或配置浏览器 Cookie/代理。",
            tail_lines(text),
        )
    if "timed out" in lower or "timeout" in lower or "urlopen error" in lower:
        return UserError(
            "连接 YouTube 超时。",
            "检查网络连接；如有需要，设置 YTDLP_PROXY 代理后重试。",
            tail_lines(text),
        )
    if "unsupported url" in lower:
        return UserError("暂不支持这个链接类型。", "请使用单个 YouTube 视频链接。", tail_lines(text))

    error_line = ""
    for line in reversed(text.splitlines()):
        if "ERROR:" in line:
            error_line = line.split("ERROR:", 1)[1].strip()
            break
    if not error_line:
        error_line = tail_lines(text, 3) or "未知错误"
    return UserError("下载失败：" + error_line[:400], "请查看详细信息，或更新 yt-dlp 后重试。", tail_lines(text))


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------
def _codec_name(codec: str | None) -> str:
    codec = (codec or "").lower()
    if codec.startswith("avc") or codec.startswith("h264"):
        return "H.264"
    if codec.startswith("av01"):
        return "AV1"
    if codec.startswith(("vp9", "vp09")):
        return "VP9"
    if codec.startswith(("hev", "hvc")):
        return "HEVC"
    if codec.startswith("mp4a") or codec.startswith("aac"):
        return "AAC"
    if codec.startswith("opus"):
        return "Opus"
    if codec.startswith("vorbis"):
        return "Vorbis"
    return codec.split(".")[0].upper() if codec else ""


def _height_label(height: int) -> str:
    if height >= 4320:
        return f"{height}p · 8K"
    if height >= 2160:
        return f"{height}p · 4K"
    if height >= 1440:
        return f"{height}p · 2K"
    return f"{height}p"


def _format_size(fmt: dict[str, Any]) -> int:
    value = fmt.get("filesize") or fmt.get("filesize_approx") or 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def build_public_info(info: dict[str, Any]) -> dict[str, Any]:
    video_id = str(info.get("id") or "")
    formats = [f for f in (info.get("formats") or []) if isinstance(f, dict)]

    heights: dict[int, list[dict[str, Any]]] = {}
    for fmt in formats:
        if fmt.get("vcodec") in (None, "none"):
            continue
        height = fmt.get("height")
        if not isinstance(height, (int, float)) or height <= 0:
            continue
        heights.setdefault(int(height), []).append(fmt)

    resolutions: list[dict[str, Any]] = []
    for height in sorted(heights, reverse=True):
        entries = heights[height]
        codecs: list[str] = []
        for fmt in entries:
            name = _codec_name(fmt.get("vcodec"))
            if name and name not in codecs:
                codecs.append(name)
        preferred = next((c for c in ("H.264", "AV1", "VP9", "HEVC") if c in codecs), codecs[0] if codecs else "")
        fps_values = [float(f.get("fps") or 0) for f in entries]
        fps = max(fps_values) if fps_values else 0
        hdr = any(
            str(f.get("dynamic_range") or "SDR").upper() not in ("SDR", "NONE")
            or "hdr" in str(f.get("format_note") or "").lower()
            for f in entries
        )
        sizes = [size for size in (_format_size(f) for f in entries) if size > 0]
        resolutions.append(
            {
                "height": height,
                "label": _height_label(height),
                "fps": round(fps, 2) if fps else 0,
                "hdr": hdr,
                "codec": preferred,
                "codecs": codecs,
                "size_estimate": min(sizes) if sizes else 0,
            }
        )

    audio_only = [
        f for f in formats
        if f.get("acodec") not in (None, "none") and f.get("vcodec") in (None, "none")
    ]
    has_audio = any(f.get("acodec") not in (None, "none") for f in formats)
    best_audio = max(
        audio_only,
        key=lambda f: (float(f.get("abr") or f.get("tbr") or 0), _format_size(f)),
        default=None,
    )

    raw_date = str(info.get("upload_date") or "")
    upload_date = ""
    if re.fullmatch(r"\d{8}", raw_date):
        upload_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"

    available_heights = {item["height"] for item in resolutions}
    if 1080 in available_heights:
        default_height = 1080
    else:
        lower = [h for h in available_heights if h <= 1080]
        default_height = max(lower) if lower else (max(available_heights) if available_heights else None)

    thumbnails = []
    for quality, config in THUMB_QUALITIES.items():
        thumbnails.append(
            {
                "id": quality,
                "label": config["label"],
                "detail": config["detail"],
                "url": f"/api/thumbnail/{video_id}?q={quality}",
            }
        )

    duration = info.get("duration")
    try:
        duration = int(duration) if duration is not None else 0
    except (TypeError, ValueError):
        duration = 0

    def int_or_zero(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    return {
        "id": video_id,
        "url": f"https://www.youtube.com/watch?v={video_id}",
        "title": str(info.get("title") or "未命名视频"),
        "uploader": str(info.get("uploader") or info.get("channel") or "未知频道"),
        "channel_url": str(info.get("channel_url") or ""),
        "duration": duration,
        "view_count": int_or_zero(info.get("view_count")),
        "like_count": int_or_zero(info.get("like_count")),
        "upload_date": upload_date,
        "webpage_url": str(info.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}"),
        "thumbnail": f"/api/thumbnail/{video_id}?q=hq",
        "thumbnails": thumbnails,
        "resolutions": resolutions,
        "default_height": default_height,
        "has_audio": has_audio,
        "audio": {
            "codec": _codec_name(best_audio.get("acodec")) if best_audio else "",
            "ext": str(best_audio.get("ext") or "") if best_audio else "",
            "abr": round(float(best_audio.get("abr") or best_audio.get("tbr") or 0), 1) if best_audio else 0,
        },
        "is_live": bool(info.get("is_live")),
        "was_live": bool(info.get("was_live")),
    }


_info_cache: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
_info_cache_lock = threading.Lock()
INFO_CACHE_TTL = 10 * 60


def get_cached_info(video_id: str) -> dict[str, Any] | None:
    now = time.time()
    with _info_cache_lock:
        entry = _info_cache.get(video_id)
        if not entry:
            return None
        created, value = entry
        if now - created > INFO_CACHE_TTL:
            _info_cache.pop(video_id, None)
            return None
        _info_cache.move_to_end(video_id)
        return value


def cache_info(video_id: str, value: dict[str, Any]) -> None:
    with _info_cache_lock:
        _info_cache[video_id] = (time.time(), value)
        _info_cache.move_to_end(video_id)
        while len(_info_cache) > 24:
            _info_cache.popitem(last=False)


def extract_info(url: str) -> dict[str, Any]:
    video_id, canonical = parse_youtube_url(url)
    cached = get_cached_info(video_id)
    if cached:
        return cached

    cmd = ytdlp_command() + [
        "--dump-single-json",
        "--skip-download",
        canonical,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=75,
            env=subprocess_env(),
            **popen_extra(),
        )
    except subprocess.TimeoutExpired as exc:
        raise UserError(
            "解析超时，YouTube 响应过慢。",
            "检查网络连接，或配置 YTDLP_PROXY 代理后重试。",
        ) from exc
    except OSError as exc:
        raise UserError("无法启动 yt-dlp。", "请运行 update-ytdlp.bat 修复运行环境。", str(exc)) from exc

    raw = (proc.stdout or "").strip()
    if proc.returncode != 0 or not raw:
        raise friendly_error(proc.stderr or proc.stdout or "yt-dlp 没有返回数据")

    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise UserError("解析 YouTube 返回数据失败。", "请稍后重试，或更新 yt-dlp。", str(exc)) from exc

    if info.get("_type") in ("playlist", "multi_video"):
        raise UserError("这是一个播放列表，当前只支持单个视频。", "请复制单个视频的链接。")
    if not VIDEO_ID_RE.match(str(info.get("id") or "")):
        raise UserError("YouTube 没有返回有效的视频信息。", "请确认链接是否有效。")
    if info.get("is_live"):
        raise UserError("暂不支持正在直播的流。", "直播结束后再下载回放。")

    public = build_public_info(info)
    cache_info(video_id, public)
    return public


# ---------------------------------------------------------------------------
# Thumbnail proxy / fetching
# ---------------------------------------------------------------------------
_thumb_cache: OrderedDict[tuple[str, str], tuple[bytes, str, str]] = OrderedDict()
_thumb_lock = threading.Lock()


def fetch_thumbnail(video_id: str, quality: str) -> tuple[bytes, str, str]:
    """Return ``(image_bytes, actual_quality, content_type)`` for a known video id."""
    if not VIDEO_ID_RE.match(video_id or ""):
        raise UserError("无效的视频 ID。")
    quality = quality if quality in THUMB_QUALITIES else "hq"
    key = (video_id, quality)
    with _thumb_lock:
        cached = _thumb_cache.get(key)
        if cached:
            _thumb_cache.move_to_end(key)
            return cached

    for candidate in THUMB_QUALITIES[quality]["files"]:
        url = f"https://i.ytimg.com/vi/{video_id}/{candidate}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Referer": "https://www.youtube.com/"},
        )
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                data = response.read()
                content_type = response.headers.get("Content-Type", "image/jpeg")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
            continue
        except OSError:
            continue

        if not data or len(data) < 200:
            continue
        if not (data.startswith(b"\xff\xd8") or data.startswith(b"\x89PNG")):
            continue
        actual = THUMB_FILE_TO_QUALITY.get(candidate, quality)
        result = (data, actual, "image/png" if data.startswith(b"\x89PNG") else "image/jpeg")
        with _thumb_lock:
            _thumb_cache[key] = result
            _thumb_cache.move_to_end(key)
            while len(_thumb_cache) > 24:
                _thumb_cache.popitem(last=False)
        return result

    raise UserError(
        "封面图片下载失败。",
        "可能是网络问题，或该视频没有这个尺寸的封面；请改选其他尺寸。",
    )


def save_thumbnail(video_id: str, quality: str, title: str, destination_dir: Path) -> Path:
    """Save a cover image and return its path (useful for scripted use)."""
    data, actual, content_type = fetch_thumbnail(video_id, quality)
    ext = ".png" if content_type == "image/png" else ".jpg"
    base = safe_filename(f"{title} [{video_id}] - {actual}") or f"{video_id} - cover"
    path = destination_dir / (base + ext)
    path.write_bytes(data)
    return path


# ---------------------------------------------------------------------------
# Filenames and files
# ---------------------------------------------------------------------------
_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(value: str, limit: int = 150) -> str:
    value = _INVALID_FILENAME.sub(" ", value or "")
    value = re.sub(r"\s+", " ", value).strip(" .")
    if len(value) > limit:
        value = value[:limit].rstrip(" .")
    return value


def unique_destination(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for index in range(2, 1000):
        candidate = path.with_name(f"{stem} ({index}){suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem} ({uuid.uuid4().hex[:6]}){suffix}")


def move_results(staging: Path, destination: Path) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    if not staging.exists():
        return files
    for source in sorted(staging.rglob("*")):
        if not source.is_file():
            continue
        if source.suffix.lower() in {".part", ".ytdl", ".temp", ".tmp"}:
            continue
        if source.stat().st_size <= 0:
            continue
        target = unique_destination(destination / source.name)
        shutil.move(str(source), str(target))
        files.append(
            {
                "name": target.name,
                "path": str(target),
                "size": target.stat().st_size,
            }
        )
    return files


# ---------------------------------------------------------------------------
# Download jobs
# ---------------------------------------------------------------------------
class Job:
    def __init__(self, kind: str, video_id: str, url: str, title: str, spec: str, options: dict[str, Any]):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.video_id = video_id
        self.url = url
        self.title = title or f"YouTube {video_id}"
        self.spec = spec
        self.options = options
        self.status = "queued"  # queued | downloading | processing | completed | failed | cancelled | cancelling
        self.progress = 0.0
        self.speed = 0.0
        self.eta: int | None = None
        self.downloaded = 0
        self.total = 0
        self.filename = ""
        self.files: list[dict[str, Any]] = []
        self.error = ""
        self.error_hint = ""
        self.error_detail = ""
        self.created_at = now_iso()
        self.created_ts = time.time()
        self.finished_at = ""
        self.cancel_requested = False
        self.process: subprocess.Popen[str] | None = None
        self._tail: list[str] = []

    def add_tail(self, line: str) -> None:
        line = line.strip()
        if line:
            self._tail.append(line)
            if len(self._tail) > 50:
                del self._tail[:-50]

    def tail_text(self) -> str:
        return "\n".join(self._tail[-30:])

    def snapshot(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "video_id": self.video_id,
            "url": self.url,
            "title": self.title,
            "spec": self.spec,
            "status": self.status,
            "progress": round(max(0.0, min(100.0, self.progress)), 1),
            "speed": self.speed,
            "eta": self.eta,
            "downloaded": self.downloaded,
            "total": self.total,
            "filename": self.filename,
            "files": list(self.files),
            "error": self.error,
            "error_hint": self.error_hint,
            "error_detail": self.error_detail,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


def build_spec(kind: str, options: dict[str, Any]) -> str:
    if kind in ("video", "muted"):
        height = options.get("height", "best")
        label = "最佳画质" if height == "best" else f"{height}p"
        if kind == "muted" or options.get("muted"):
            return f"{label} · 仅画面"
        suffix = " · H.264" if options.get("compat", True) else ""
        return f"{label} · 含音轨{suffix}"
    if kind == "audio":
        fmt = str(options.get("audio_format", "mp3"))
        if fmt == "best":
            return "原始音轨"
        quality = options.get("audio_quality")
        return f"{fmt.upper()}" + (f" · {quality} kbps" if quality else "")
    if kind == "thumbnail":
        quality = str(options.get("thumb_quality", "maxres"))
        config = THUMB_QUALITIES.get(quality, THUMB_QUALITIES["maxres"])
        return f"封面 · {config['label']}"
    return ""


def build_download_command(job: Job, staging: Path) -> list[str]:
    options = job.options
    ffmpeg, _ = find_ffmpeg()
    cmd = ytdlp_command() + [
        "--newline",
        "--progress",
        "--progress-template",
        PROGRESS_TEMPLATE,
        "--no-overwrites",
        "--windows-filenames",
        "--trim-filenames",
        "140",
        "-P",
        str(staging),
    ]
    if ffmpeg:
        cmd.extend(["--ffmpeg-location", str(ffmpeg)])

    if job.kind in ("video", "muted"):
        template = "%(title).150B [%(id)s] - %(height)sp.%(ext)s"
        height = options.get("height", "best")
        height_filter = "" if height == "best" else f"[height={int(height)}]"
        muted = job.kind == "muted" or bool(options.get("muted"))
        if muted:
            selector = f"bv{height_filter}/bv*{height_filter}[acodec=none]"
        elif options.get("compat", True):
            selector = (
                f"bv*{height_filter}[vcodec^=avc1]+ba[acodec^=mp4a]/"
                f"bv*{height_filter}+ba/b{height_filter}"
            )
        else:
            selector = f"bv*{height_filter}+ba/b{height_filter}"
        cmd.extend(["-f", selector, "-o", template])
        if not muted:
            cmd.extend(["--merge-output-format", "mp4"])
    elif job.kind == "audio":
        template = "%(title).150B [%(id)s].%(ext)s"
        audio_format = str(options.get("audio_format", "mp3"))
        cmd.extend(
            [
                "-f",
                "ba/b",
                "-x",
                "--audio-format",
                audio_format if audio_format in AUDIO_FORMATS else "mp3",
                "-o",
                template,
            ]
        )
        quality = options.get("audio_quality")
        if quality and audio_format not in ("best", "wav"):
            cmd.extend(["--audio-quality", f"{int(quality)}K"])
    else:
        raise UserError("不支持的下载类型。")

    cmd.append(job.url)
    return cmd


class DownloadManager:
    def __init__(self, max_workers: int = 2):
        self.max_workers = max_workers
        self._semaphore = threading.Semaphore(max_workers)
        self._lock = threading.RLock()
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._threads: list[threading.Thread] = []
        self._shutting_down = False
        ensure_dirs()

    # -- public API ---------------------------------------------------------
    def start(self, kind: str, video_id: str, url: str, title: str, options: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            active = sum(1 for job in self._jobs.values() if job.status in {"queued", "downloading", "processing", "cancelling"})
            if active >= 8:
                raise UserError("同时下载的任务太多了。", "请等待队列中的任务完成后再添加。")
            job = Job(kind, video_id, url, title, build_spec(kind, options), options)
            self._jobs[job.id] = job
            self._prune_locked()
            thread = threading.Thread(target=self._run, args=(job,), name=f"download-{job.id}", daemon=True)
            self._threads.append(thread)
        thread.start()
        return job.snapshot()

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda item: item.created_ts, reverse=True)
            return [job.snapshot() for job in jobs]

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            if job.status in {"completed", "failed", "cancelled"}:
                return True
            job.cancel_requested = True
            if job.status == "queued":
                job.status = "cancelled"
                job.finished_at = now_iso()
                return True
            job.status = "cancelling"
            process = job.process
        if process:
            self._terminate_process(process)
        return True

    def shutdown(self) -> None:
        with self._lock:
            self._shutting_down = True
            active = list(self._jobs.values())
        for job in active:
            if job.status in {"queued", "downloading", "processing", "cancelling"}:
                self.cancel(job.id)
        for thread in list(self._threads):
            thread.join(timeout=2)

    # -- internals ----------------------------------------------------------
    def _prune_locked(self) -> None:
        finished = [job for job in self._jobs.values() if job.status in {"completed", "failed", "cancelled"}]
        if len(finished) <= 40:
            return
        for job in sorted(finished, key=lambda item: item.created_ts)[: len(finished) - 40]:
            self._jobs.pop(job.id, None)

    @staticmethod
    def _terminate_process(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    capture_output=True,
                    timeout=10,
                    creationflags=CREATE_NO_WINDOW,
                )
            else:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass

    def _run(self, job: Job) -> None:
        staging = WORK_DIR / job.id
        try:
            staging.mkdir(parents=True, exist_ok=True)
            with self._semaphore:
                if self._shutting_down or job.cancel_requested:
                    self._mark_cancelled(job)
                    return
                if job.kind == "thumbnail":
                    self._run_thumbnail(job, staging)
                else:
                    self._run_ytdlp(job, staging)
        except UserError as exc:
            self._mark_failed(job, exc)
        except Exception as exc:  # noqa: BLE001 - surface unexpected errors to UI
            self._mark_failed(
                job,
                UserError("下载器内部错误。", "请重试；若持续出现，请查看程序控制台输出。", f"{type(exc).__name__}: {exc}"),
            )
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _run_thumbnail(self, job: Job, staging: Path) -> None:
        with self._lock:
            if job.cancel_requested:
                self._mark_cancelled(job)
                return
            job.status = "downloading"
            job.progress = 8
        quality = str(job.options.get("thumb_quality", "maxres"))
        data, actual, content_type = fetch_thumbnail(job.video_id, quality)
        with self._lock:
            if job.cancel_requested:
                self._mark_cancelled(job)
                return
            job.progress = 65
        ext = ".png" if content_type == "image/png" else ".jpg"
        base = safe_filename(f"{job.title} [{job.video_id}] - cover") or f"{job.video_id} - cover"
        (staging / (base + ext)).write_bytes(data)
        with self._lock:
            if job.cancel_requested:
                self._mark_cancelled(job)
                return
            job.progress = 92
        files = move_results(staging, DOWNLOAD_DIR)
        if not files:
            raise UserError("封面已获取，但写入文件失败。", "请检查下载目录是否可写。")
        actual_config = THUMB_QUALITIES.get(actual, THUMB_QUALITIES[quality])
        with self._lock:
            job.spec = f"封面 · {actual_config['label']}"
            job.files = files
            job.filename = files[0]["name"]
            job.status = "completed"
            job.progress = 100
            job.finished_at = now_iso()

    def _run_ytdlp(self, job: Job, staging: Path) -> None:
        with self._lock:
            if job.cancel_requested:
                self._mark_cancelled(job)
                return
            job.status = "downloading"
            job.progress = 0
        cmd = build_download_command(job, staging)
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                env=subprocess_env(),
                **popen_extra(),
            )
        except OSError as exc:
            raise UserError("无法启动 yt-dlp 进程。", "请运行 update-ytdlp.bat 修复运行环境。", str(exc)) from exc

        with self._lock:
            job.process = process
            if job.cancel_requested:
                self._terminate_process(process)

        assert process.stdout is not None
        for line in process.stdout:
            self._handle_output(job, line)
        returncode = process.wait()

        with self._lock:
            job.process = None
        if job.cancel_requested:
            self._mark_cancelled(job)
            return
        if returncode != 0:
            detail = job.tail_text()
            raise friendly_error(detail or f"yt-dlp 退出码 {returncode}")

        files = move_results(staging, DOWNLOAD_DIR)
        if not files:
            raise UserError("下载完成但没有找到输出文件。", "请检查下载目录，或更新 yt-dlp 后重试。", job.tail_text())
        primary = max(files, key=lambda item: item.get("size", 0))
        with self._lock:
            job.files = files
            job.filename = primary["name"]
            job.status = "completed"
            job.progress = 100
            job.eta = 0
            job.finished_at = now_iso()

    def _handle_output(self, job: Job, line: str) -> None:
        line = line.replace("\r", "").strip()
        if not line:
            return
        job.add_tail(line)
        if PROGRESS_MARKER in line:
            payload = line.split(PROGRESS_MARKER, 1)[1]
            parts = payload.split("|")
            try:
                downloaded = self._number(parts[0]) if len(parts) > 0 else 0
                total = self._number(parts[1]) if len(parts) > 1 else 0
                estimate = self._number(parts[2]) if len(parts) > 2 else 0
                speed = self._number(parts[3]) if len(parts) > 3 else 0
                eta = self._number(parts[4]) if len(parts) > 4 else 0
                percent = self._percent(parts[5]) if len(parts) > 5 else 0
                if not total:
                    total = estimate
                if percent <= 0 and total and downloaded:
                    percent = downloaded / total * 100
                with self._lock:
                    if job.status not in {"downloading", "processing"}:
                        return
                    if job.status == "downloading":
                        job.progress = max(0.0, min(99.9, percent))
                    job.downloaded = int(downloaded)
                    job.total = int(total)
                    job.speed = float(speed)
                    job.eta = int(eta) if eta else None
            except (ValueError, TypeError, IndexError):
                return
            return

        lower = line.lower()
        if any(token in lower for token in ("[merger]", "[extractaudio]", "[videoconvertor]", "[fixupm3u8]", "[fixupm4a]")):
            with self._lock:
                if job.status == "downloading":
                    job.status = "processing"
                    job.progress = max(job.progress, 99.0)
                    job.eta = None

    @staticmethod
    def _number(value: str) -> float:
        value = (value or "").strip()
        if not value or value.upper() in {"NA", "NONE", "UNKNOWN"}:
            return 0
        return float(value)

    @staticmethod
    def _percent(value: str) -> float:
        value = (value or "").replace("%", "").strip()
        if not value or value.upper() in {"NA", "NONE", "UNKNOWN"}:
            return 0
        return float(value)

    def _mark_failed(self, job: Job, error: UserError) -> None:
        with self._lock:
            if job.cancel_requested:
                job.status = "cancelled"
                job.finished_at = now_iso()
                return
            job.status = "failed"
            job.error = error.message
            job.error_hint = error.hint
            job.error_detail = error.detail[:3000]
            job.eta = None
            job.speed = 0
            job.finished_at = now_iso()

    def _mark_cancelled(self, job: Job) -> None:
        with self._lock:
            job.status = "cancelled"
            job.speed = 0
            job.eta = None
            job.finished_at = now_iso()
