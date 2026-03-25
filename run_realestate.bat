@echo off
chcp 65001 >nul

cd /d "C:\Users\sungh\OneDrive\Desktop\기사수집"

set LOGFILE=realestate_log.txt
echo ============================================== >> %LOGFILE%
echo [%date% %time%] Starting Real Estate auto collection... >> %LOGFILE%

:: 1. 기사 수집
echo [%date% %time%] Step 1: collect_realestate.py >> %LOGFILE%
python collect_realestate.py >> %LOGFILE% 2>&1
if errorlevel 1 (
    echo [%date% %time%] [FAIL] collect_realestate.py failed >> %LOGFILE%
    exit /b 1
)
echo [%date% %time%] [OK] collect_realestate.py >> %LOGFILE%

:: 2. Daily Top 20 HTML 보고서
echo [%date% %time%] Step 2: daily_realestate.py >> %LOGFILE%
python daily_realestate.py >> %LOGFILE% 2>&1
if errorlevel 1 (
    echo [%date% %time%] [FAIL] daily_realestate.py failed >> %LOGFILE%
    exit /b 1
)
echo [%date% %time%] [OK] daily_realestate.py >> %LOGFILE%

:: 3. Discord 전송
echo [%date% %time%] Step 3: discord_realestate.py >> %LOGFILE%
python discord_realestate.py >> %LOGFILE% 2>&1
if errorlevel 1 (
    echo [%date% %time%] [FAIL] discord_realestate.py failed >> %LOGFILE%
    exit /b 1
)
echo [%date% %time%] [OK] discord_realestate.py >> %LOGFILE%

echo [%date% %time%] ALL DONE >> %LOGFILE%
