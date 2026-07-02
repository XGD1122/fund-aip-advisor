@echo off
cd /d D:\A001-fund\fund-aip-advisor-main\backend
python refresh_data.py
echo Data refresh completed at %date% %time% >> refresh_log.txt
