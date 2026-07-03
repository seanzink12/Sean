@echo off
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo Python is not installed or not on PATH. Install Python from python.org and try again.
    pause
    exit /b 1
)

echo Installing/checking dependencies...
pip install -r requirements.txt -q

echo Starting Interior Design Image Scraper...
streamlit run app.py

pause
