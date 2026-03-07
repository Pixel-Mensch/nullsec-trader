@echo off
cd /d "%~dp0"
python --version >nul 2>&1
if errorlevel 1 (
  echo Python wurde nicht gefunden. Bitte Python 3.10+ installieren und erneut starten.
  pause
  exit /b 1
)
python -m pip show requests >nul 2>&1
if errorlevel 1 (
  echo Installiere Abhaengigkeiten...
  python -m pip install --user requests
)
for /f "tokens=1,2" %%A in ('python -c "import json; cfg=json.load(open('config.json', encoding='utf-8-sig')); print(int(cfg['defaults']['cargo_m3']), int(cfg['defaults']['budget_isk']))"') do (
  set "CARGO_M3=%%A"
  set "BUDGET_ISK=%%B"
)
if not defined CARGO_M3 set "CARGO_M3=10000"
if not defined BUDGET_ISK set "BUDGET_ISK=500000000"
echo Starte Nullsec Trader im Live-Modus mit Cargo %CARGO_M3% und Budget %BUDGET_ISK%...
python main.py --cargo-m3 %CARGO_M3% --budget-isk %BUDGET_ISK%
pause
