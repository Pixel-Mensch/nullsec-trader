@echo off
setlocal
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
  echo Python wurde nicht gefunden. Bitte Python 3.10+ installieren und erneut starten.
  pause
  exit /b 1
)

python -c "import fastapi, jinja2, uvicorn, multipart" >nul 2>&1
if errorlevel 1 (
  echo Installiere Web-Abhaengigkeiten...
  python -m pip install --user -r requirements.txt
  if errorlevel 1 (
    echo Installation der Web-Abhaengigkeiten ist fehlgeschlagen.
    pause
    exit /b 1
  )
)

set "WEB_URL=http://127.0.0.1:8000"
echo Starte Nullsec Trader Web...
start "Nullsec Trader Web" cmd /k "cd /d ""%~dp0"" && python -c ""from webapp.app import run_dev_server; run_dev_server()"""
timeout /t 2 /nobreak >nul
start "" "%WEB_URL%"
echo Browser geoeffnet: %WEB_URL%
echo Zum Beenden das Fenster "Nullsec Trader Web" schliessen oder Strg+C druecken.
