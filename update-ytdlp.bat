@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

set "PYTHON=python"
where python >nul 2>nul
if errorlevel 1 (
    where py >nul 2>nul
    if errorlevel 1 (
        echo [错误] 未找到 Python，无法更新 yt-dlp。
        pause
        exit /b 1
    )
    set "PYTHON=py -3"
)

echo.
echo 正在更新 yt-dlp 到最新版本...
echo YouTube 经常调整接口，下载失败时先运行本脚本往往能解决。
echo.
%PYTHON% -m pip install --upgrade --target vendor --no-cache-dir yt-dlp
if errorlevel 1 (
    echo.
    echo [错误] 更新失败，请检查网络连接后重试。
    pause
    exit /b 1
)

echo.
%PYTHON% -c "import sys; sys.path.insert(0, 'vendor'); import yt_dlp; print('当前 yt-dlp 版本:', yt_dlp.version.__version__)"
echo.
echo 更新完成。
pause
