@echo off
REM Activate ebook_capture .venv (Python 3.11) in cmd.exe.
REM Usage: activate.cmd
REM    or: cmd /k activate.cmd

set "VENV_DIR=%~dp0.venv"
if not exist "%VENV_DIR%\Scripts\activate.bat" (
    echo [error] Virtual environment not found: %VENV_DIR%
    echo Run: uv venv --python 3.11
    exit /b 1
)

call "%VENV_DIR%\Scripts\activate.bat"
if errorlevel 1 exit /b 1

echo [ok] ebook_capture venv active ^(Python 3.11^)
python --version
