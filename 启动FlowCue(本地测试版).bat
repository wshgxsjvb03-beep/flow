@echo off
cd /d "%~dp0"
taskkill /F /IM FlowCue.exe >nul 2>&1
"C:\Users\DYcomputer\AppData\Local\Programs\Python\Python313\python.exe" main.py
if errorlevel 1 pause
