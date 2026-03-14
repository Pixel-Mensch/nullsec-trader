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
set "SERVER_SCRIPT=%~dp0start_webapp_server.bat"

echo Starte Nullsec Trader Web...
start "Nullsec Trader Web" cmd /k call "%SERVER_SCRIPT%"

powershell -NoProfile -Command "$deadline=(Get-Date).AddSeconds(20); while ((Get-Date) -lt $deadline) { try { $resp = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8000/' -TimeoutSec 2; if ($resp.StatusCode -ge 200) { exit 0 } } catch {}; Start-Sleep -Milliseconds 500 }; exit 1" >nul 2>&1

if errorlevel 1 (
  echo Der Web-Server hat nicht rechtzeitig geantwortet.
  echo Bitte das Fenster "Nullsec Trader Web" pruefen.
  pause
  exit /b 1
)

start "" "%WEB_URL%"
echo Browser geoeffnet: %WEB_URL%
echo Zum Beenden das Fenster "Nullsec Trader Web" schliessen oder Strg+C druecken.
exit /b 0
