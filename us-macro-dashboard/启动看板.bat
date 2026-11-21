@echo off
rem US Macro Dashboard launcher
rem Double-click this file to start the local service (daemon) and open the page.
cd /d "%~dp0"

set "PYW=C:\Users\weilei\anaconda3\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"

start "" "%PYW%" "%~dp0scripts\daemon.py"

rem wait for the static server to be ready (max ~10s)
set /a n=0
:waitloop
set /a n+=1
>nul 2>&1 curl -s -o nul --max-time 1 http://127.0.0.1:43187/index.html
if not errorlevel 1 goto ready
if %n% geq 10 goto ready
>nul 2>&1 ping -n 2 127.0.0.1
goto waitloop

:ready
start "" "http://127.0.0.1:43187/index.html"
exit
