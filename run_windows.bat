@echo off
REM Windows: double-click this file to open the demo in your browser.
cd /d %~dp0
if not exist .venv python -m venv .venv
call .venv\Scripts\activate
pip install -q -r requirements.txt
streamlit run app.py
pause
