@echo off
setlocal
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto :failed
.venv\Scripts\python.exe -m pip install -r requirements-build.txt
if errorlevel 1 goto :failed
.venv\Scripts\python.exe -m unittest discover -s tests -v
if errorlevel 1 goto :failed
.venv\Scripts\python.exe build_gui.py
if errorlevel 1 goto :failed
echo Built: %~dp0dist\XMiniICCIDReader.exe
pause
exit /b 0

:failed
echo Build failed. See the error above.
pause
exit /b 1
