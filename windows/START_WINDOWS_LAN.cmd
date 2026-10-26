@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo Запуск на домашней сети: показывайте URL только доверенным устройствам.
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  py -3 app.py --host 0.0.0.0
) else (
  python app.py --host 0.0.0.0
)
pause
