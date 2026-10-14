@echo off
chcp 65001 >nul
REM Windows: double-click this file to open the demo in your browser.
REM Prepares Python 3.12 automatically, regardless of the Python installed on this PC.
cd /d %~dp0
set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"

echo Preparing the demo. The first run can take 2-3 minutes. Please keep this window open.

where uv >nul 2>nul
if errorlevel 1 (
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  set "PATH=%USERPROFILE%\.local\bin;%USERPROFILE%\.cargo\bin;%PATH%"
)

if not exist .venv312\Scripts\python.exe (
  uv venv --python 3.12 .venv312
  if errorlevel 1 goto fail
)

uv pip install --python .venv312\Scripts\python.exe -q -r requirements.txt
if errorlevel 1 goto fail

if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
  echo [general]> "%USERPROFILE%\.streamlit\credentials.toml"
  echo email = "">> "%USERPROFILE%\.streamlit\credentials.toml"
)

.venv312\Scripts\python.exe -m streamlit run app.py --browser.gatherUsageStats false
pause
exit /b

:fail
echo Setup failed. Please take a screenshot of this window.
pause
