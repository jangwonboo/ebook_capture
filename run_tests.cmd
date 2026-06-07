@echo off
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set PY=.venv\Scripts\python.exe
) else (
  set PY=python
)

echo Installing test deps if needed...
uv pip install -q -e ".[dev]" 2>nul
if errorlevel 1 "%PY%" -m pip install -q -e ".[dev]" 2>nul

echo.
echo Running pytest...
"%PY%" -m pytest tests %*
set EXIT_CODE=%ERRORLEVEL%

if %EXIT_CODE% neq 0 exit /b %EXIT_CODE%
echo.
echo All tests passed.
exit /b 0
