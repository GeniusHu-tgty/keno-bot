@echo off
setlocal
cd /d "%~dp0"

rem 优先启动已打包的 exe；没有就跑本机 Python（需要 3.11+）
if exist "dist\KenoBOT.exe" (
    start "" "dist\KenoBOT.exe"
    exit /b 0
)

where python >nul 2>nul
if errorlevel 1 (
    echo [Keno BOT] 没有找到 python，也没有 dist\KenoBOT.exe。
    echo 请安装 Python 3.11+ 并勾选 Add to PATH，或先运行 build_exe.ps1 生成 exe。
    pause
    exit /b 1
)

set "PYTHONPATH=%~dp0src"
python "%~dp0keno_bot_app.py"
if errorlevel 1 pause
endlocal
