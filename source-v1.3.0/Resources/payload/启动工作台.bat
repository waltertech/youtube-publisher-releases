@echo off
set PYTHONUTF8=1
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
 py -3 -m venv .venv
 if errorlevel 1 goto fail
 .venv\Scripts\python.exe -m pip install -r requirements.txt
 if errorlevel 1 goto fail
)
if not exist 本机配置.json (
 .venv\Scripts\python.exe setup_local.py
 if errorlevel 1 goto fail
)
.venv\Scripts\python.exe dashboard.py
goto :eof
:fail
pause
