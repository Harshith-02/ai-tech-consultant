@echo off
echo =======================================================
echo LAUNCHING AI TECH CONSULTANT
echo =======================================================
cd /d "%~dp0"
.venv\Scripts\python.exe scripts\start_services.py
pause
