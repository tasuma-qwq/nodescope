@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    py -3 -m venv .venv
    if errorlevel 1 goto failed
)
".venv\Scripts\python.exe" -c "import web" >nul 2>&1
if errorlevel 1 (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto failed
)
echo NodeScope - open http://127.0.0.1:8080 in your browser.
echo Keep this window open. Press Ctrl+C to stop.
".venv\Scripts\python.exe" web.py
if errorlevel 1 goto failed
exit /b 0
:failed
echo NodeScope could not start. Check Python 3.10+ and your network connection.
pause
exit /b 1
