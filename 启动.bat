@echo off
rem Keno BOT launcher.
rem Keep this file ASCII-only and CRLF-terminated: cmd.exe reads .bat with the
rem OEM codepage, and a LF-only or non-ASCII file breaks on multibyte characters.
setlocal enableextensions
cd /d "%~dp0"

rem PyInstaller onefile unpacks itself into TEMP before Python starts. Point TEMP
rem at a folder we verified is writable: the user profile, then this folder.
set "KBTMP="
call :try_tmp "%~dp0tmp"
if not defined KBTMP call :try_tmp "%LOCALAPPDATA%\KenoBOT\tmp"
if not defined KBTMP call :try_tmp "%TEMP%"
if defined KBTMP set "TEMP=%KBTMP%"
if defined KBTMP set "TMP=%KBTMP%"

rem Two layouts: release zip (exe next to this file) and source checkout (dist\).
if exist "KenoBOT.exe" goto run_exe_here
if exist "dist\KenoBOT.exe" goto run_exe_dist
goto run_src

:run_exe_here
start "" "KenoBOT.exe"
goto verify

:run_exe_dist
start "" "dist\KenoBOT.exe"

:verify
rem give the packaged app a few seconds, then check that it is still alive
ping -n 6 127.0.0.1 >nul
tasklist /fi "imagename eq KenoBOT.exe" 2>nul | find /i "KenoBOT.exe" >nul
if not errorlevel 1 goto done
echo [Keno BOT] the packaged KenoBOT.exe exited right away; trying the Python source instead.

:run_src
where python >nul 2>nul
if errorlevel 1 goto no_python
set "PYTHONPATH=%~dp0src"
python "%~dp0keno_bot_app.py"
if errorlevel 1 pause
goto done

:no_python
echo [Keno BOT] Neither KenoBOT.exe nor Python 3.11+ was found.
echo Download the release zip again, or install Python 3.11+ (tick "Add python.exe to PATH").
pause
goto done

:try_tmp
if defined KBTMP goto :eof
if not exist "%~1" mkdir "%~1" >nul 2>nul
if not exist "%~1" goto :eof
echo probe > "%~1\_kb_probe.tmp" 2>nul
if not exist "%~1\_kb_probe.tmp" goto :eof
del "%~1\_kb_probe.tmp" >nul 2>nul
set "KBTMP=%~1"
goto :eof

:done
endlocal
