@echo off
cd /d "%~dp0"

python --version >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Close this window, reopen a NEW terminal ^(so it picks up
    echo a fresh PATH^), and try again. If it still fails, install Python from python.org.
    pause
    exit /b 1
)

echo Installing/checking dependencies...
python -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo pip install failed - see the error above.
    pause
    exit /b 1
)

echo Starting Cognitive Load Design Critic...
python -m streamlit run app.py

pause
