@echo off
chcp 65001 >nul
echo [%date% %time%] Starting HBF auto collection...

cd /d "C:\Users\sungh\OneDrive\Desktop\기사수집"

:: 1. 기사 수집
python collect_hbf.py
if errorlevel 1 (
    echo [ERROR] collect_hbf.py failed
    exit /b 1
)

:: 2. Daily Top 10 HTML 보고서
python daily_top10.py

:: 3. Discord 전송
python discord_send.py

echo [%date% %time%] Done! >> auto_collect.log
