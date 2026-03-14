@echo off
setlocal
cd /d "%~dp0"
python -m uvicorn webapp.app:create_app --factory --host 127.0.0.1 --port 8000
