@echo off
cd /d "%~dp0"
if not exist data mkdir data
set PYTHONIOENCODING=utf-8
python main.py diario > data\ultimo_log.txt 2>&1
