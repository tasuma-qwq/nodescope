@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
pushd "%~dp0"
if exist ".venv\Scripts\python.exe" goto existing
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 goto python
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if not errorlevel 1 goto launcher
echo Python 3.10+ is required. Install Python, then double-click this file again.
set "DETECT_EXIT=1"
goto finished
:existing
".venv\Scripts\python.exe" scripts\launch_cli.py %*
set "DETECT_EXIT=%ERRORLEVEL%"
goto finished
:launcher
py -3 scripts\launch_cli.py %*
set "DETECT_EXIT=%ERRORLEVEL%"
goto finished
:python
python scripts\launch_cli.py %*
set "DETECT_EXIT=%ERRORLEVEL%"
:finished
echo.
echo NodeScope finished. Results are in the exports folder.
pause
popd
exit /b %DETECT_EXIT%
