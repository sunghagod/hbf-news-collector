@echo off
chcp 65001 >nul

cd /d "C:\Users\sungh\OneDrive\Desktop\기사수집"

set LOGFILE=energy_log.txt
echo ============================================== >> %LOGFILE%
echo [%date% %time%] Starting Energy auto collection... >> %LOGFILE%

:: 1. 기사 수집
echo [%date% %time%] Step 1: collect_energy.py >> %LOGFILE%
python collect_energy.py >> %LOGFILE% 2>&1
if errorlevel 1 (
    echo [%date% %time%] [FAIL] collect_energy.py failed >> %LOGFILE%
    exit /b 1
)
echo [%date% %time%] [OK] collect_energy.py >> %LOGFILE%

:: 2. Daily Top 20 HTML 보고서
echo [%date% %time%] Step 2: daily_energy.py >> %LOGFILE%
python daily_energy.py >> %LOGFILE% 2>&1
if errorlevel 1 (
    echo [%date% %time%] [FAIL] daily_energy.py failed >> %LOGFILE%
    exit /b 1
)
echo [%date% %time%] [OK] daily_energy.py >> %LOGFILE%

:: 3. Discord 전송
echo [%date% %time%] Step 3: discord_energy.py >> %LOGFILE%
python discord_energy.py >> %LOGFILE% 2>&1
if errorlevel 1 (
    echo [%date% %time%] [FAIL] discord_energy.py failed >> %LOGFILE%
    exit /b 1
)
echo [%date% %time%] [OK] discord_energy.py >> %LOGFILE%

echo [%date% %time%] ALL DONE >> %LOGFILE%
