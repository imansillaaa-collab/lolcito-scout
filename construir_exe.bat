@echo off
rem Compila LolcitoScout.exe en tu PC (necesita Python). Lo normal es dejar que lo compile GitHub (ver PUBLICAR.md).
cd /d "%~dp0"
set DATOS=
if exist lolscout\servidor.json set DATOS=--add-data "lolscout/servidor.json;lolscout"
python -m PyInstaller --noconfirm --clean --onefile --noconsole --name LolcitoScout --icon lolscout.ico --add-data "lolscout/live/page.html;lolscout/live" --add-data "lolscout/live/static;lolscout/live/static" %DATOS% --collect-submodules lolscout app.py
echo Listo: dist\LolcitoScout.exe
pause
