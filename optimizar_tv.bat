@echo off
cd /d "%~dp0"
set PATH=%~dp0platform-tools;%PATH%
python tv_optimizer.py buscar
set /p IP=Escribe la IP del TV: 
python tv_optimizer.py todo %IP%
pause
