@echo off
setlocal
chcp 65001 >nul
title YT Grab
set "PYTHONUTF8=1"
cd /d "%~dp0"

set "PYTHON=python"
where python >nul 2>nul
if errorlevel 1 (
    where py >nul 2>nul
    if errorlevel 1 (
        echo.
        echo [错误] 未找到 Python。
        echo 请安装 Python 3.11 或更高版本：https://www.python.org/downloads/
        echo 安装时记得勾选 "Add Python to PATH"。
        echo.
        pause
        exit /b 1
    )
    set "PYTHON=py -3"
)

%PYTHON% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 (
    echo.
    echo [错误] Python 版本过低，需要 3.11 或更高版本。
    %PYTHON% --version
    echo.
    pause
    exit /b 1
)

if not exist "vendor\yt_dlp\__init__.py" (
    echo.
    echo 首次运行：正在安装下载引擎 yt-dlp...
    echo 这一步需要联网，通常只需要执行一次。
    echo.
    %PYTHON% -m pip install --disable-pip-version-check --no-warn-script-location --upgrade --target vendor --no-cache-dir yt-dlp
    if errorlevel 1 (
        echo.
        echo [错误] 自动安装 yt-dlp 失败。
        echo 请检查网络连接，或手动执行：
        echo   %PYTHON% -m pip install --target vendor yt-dlp
        echo.
        pause
        exit /b 1
    )
)

if not exist "vendor\yt_dlp\__init__.py" (
    echo.
    echo [错误] 缺少下载引擎 vendor\yt_dlp。
    echo 请双击 update-ytdlp.bat 修复，或检查网络后重试。
    echo.
    pause
    exit /b 1
)

echo 正在启动 YT Grab...
%PYTHON% app.py --open
set "EXITCODE=%ERRORLEVEL%"
echo.
if "%EXITCODE%"=="0" (
    echo 服务已停止。
) else (
    echo 程序异常退出，错误码：%EXITCODE%
)
echo.
echo 如果上方没有显示网页地址，请保留本窗口并截图反馈。
pause
exit /b %EXITCODE%
