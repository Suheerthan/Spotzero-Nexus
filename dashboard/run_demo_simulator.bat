@echo off
cd /d "%~dp0"
echo Sending FAKE demo data to the dashboard (start run_dashboard.bat first).
echo Use Reset data on the dashboard before real tests.
python simulator.py
pause
