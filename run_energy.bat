@echo off
cd /d "C:\Users\sungh\Desktop\기사수집"
echo [%date% %time%] Energy News Bot Start >> energy_log.txt

python collect_energy.py >> energy_log.txt 2>&1
python daily_energy.py >> energy_log.txt 2>&1
python discord_energy.py >> energy_log.txt 2>&1

echo [%date% %time%] Energy News Bot Done >> energy_log.txt
echo. >> energy_log.txt
