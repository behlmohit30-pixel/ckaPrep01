@echo off
rem Job hunt v3: collect, score and write today.md / today.html. Task Scheduler calls this (see setup_task.ps1).
cd /d "%~dp0"
set "JH=D:\MoBe docs\CareerIreland\JobHunt"
set "LOG=%~dp0out"
if exist "%JH%\v3_private\profile.json" set "LOG=%JH%\v3_out"
if not exist "%LOG%" mkdir "%LOG%"
call "%~dp0jh.cmd" collect >> "%LOG%\run_log.txt" 2>&1
call "%~dp0jh.cmd" today > "%LOG%\today_console.txt" 2>&1
if /I "%1"=="open" start "" "%LOG%\today.html"
