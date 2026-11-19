@echo off
cd /d "%~dp0"
python -X utf8 app.py --open
if errorlevel 1 pause
