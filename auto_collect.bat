@echo off
chcp 65001 >nul

cd /d "C:\Users\sungh\OneDrive\Desktop\기사수집"

set LOGFILE=auto_collect.log
echo ============================================== >> %LOGFILE%
echo [%date% %time%] Starting HBF auto collection... >> %LOGFILE%

:: 1. 기사 수집
echo [%date% %time%] Step 1: collect_hbf.py >> %LOGFILE%
python collect_hbf.py >> %LOGFILE% 2>&1
if errorlevel 1 (
    echo [%date% %time%] [FAIL] collect_hbf.py failed >> %LOGFILE%
    python error_notify.py "collect_hbf.py 실패" >> %LOGFILE% 2>&1
    exit /b 1
)
echo [%date% %time%] [OK] collect_hbf.py >> %LOGFILE%

:: 2. Daily Top 10 HTML 보고서
echo [%date% %time%] Step 2: daily_top10.py >> %LOGFILE%
python daily_top10.py >> %LOGFILE% 2>&1
if errorlevel 1 (
    echo [%date% %time%] [FAIL] daily_top10.py failed >> %LOGFILE%
    python error_notify.py "daily_top10.py 실패" >> %LOGFILE% 2>&1
    exit /b 1
)
echo [%date% %time%] [OK] daily_top10.py >> %LOGFILE%

:: 3. Discord 전송
echo [%date% %time%] Step 3: discord_send.py >> %LOGFILE%
python discord_send.py >> %LOGFILE% 2>&1
if errorlevel 1 (
    echo [%date% %time%] [FAIL] discord_send.py failed >> %LOGFILE%
    python error_notify.py "discord_send.py 실패" >> %LOGFILE% 2>&1
    exit /b 1
)
echo [%date% %time%] [OK] discord_send.py >> %LOGFILE%

echo [%date% %time%] ALL DONE >> %LOGFILE%
