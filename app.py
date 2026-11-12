"""YT Grab - a local YouTube video, audio and cover downloader."""
from __future__ import annotations

import argparse
import sys
import threading
import webbrowser

from server import create_server
from ytdl_core import DOWNLOAD_DIR, DownloadManager, ensure_dirs, ffmpeg_health, ytdlp_health


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="YT Grab - 本地 YouTube 下载器")
    parser.add_argument("--port", type=int, default=8765, help="本地网页端口（默认 8765）")
    parser.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    return parser.parse_args()


def main() -> int:
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, OSError):
        pass
    args = parse_args()
    ensure_dirs()
    manager = DownloadManager(max_workers=2)
    try:
        server, url = create_server(manager, preferred_port=max(1, min(args.port, 65500)))
    except RuntimeError as exc:
        print(f"[错误] {exc}")
        return 1

    ffmpeg = ffmpeg_health()
    print("=" * 62)
    print("  YT Grab · YouTube 视频 / 音频 / 封面下载器")
    print("=" * 62)
    print(f"  网页地址 : {url}")
    print(f"  下载目录 : {DOWNLOAD_DIR}")
    print(f"  yt-dlp   : {ytdlp_health()['version']}")
    if ffmpeg["available"]:
        print(f"  FFmpeg   : {ffmpeg['version']}  ({ffmpeg['path']})")
    else:
        print("  FFmpeg   : 未找到（高清视频合并和音频转换将不可用）")
    print("=" * 62)
    print("  按 Ctrl+C 停止服务")
    print()

    if args.open and not args.no_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever(poll_interval=0.4)
    except KeyboardInterrupt:
        print("\n正在停止…")
    finally:
        manager.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
