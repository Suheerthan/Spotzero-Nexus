@echo off
cd /d "%~dp0"
echo Installing requirements (first run only)...
python -m pip install -q -r requirements.txt
echo.
echo Dashboard: http://localhost:5000
echo For the ESP32, use this laptop's IPv4 address below in SERVER_URL:
ipconfig | findstr /i "IPv4"
echo.
start "" http://localhost:5000
python app.py
pause
