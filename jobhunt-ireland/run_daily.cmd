@echo off
rem Job hunt v3: collect, score and write today.md / today.html. Task Scheduler calls this (see setup_task.ps1).
rem Private facts, state and output live in the Drive-synced JobHunt folder, so they are backed up and readable on a phone.
cd /d "%~dp0"
set "JH=D:\MoBe docs\CareerIreland\JobHunt"
if exist "%JH%\v3_private\profile.json" (
  set "JH_PRIVATE=%JH%\v3_private"
  set "JH_STATE=%JH%\v3_state"
  set "JH_OUT=%JH%\v3_out"
)
if not defined JH_OUT set "JH_OUT=%~dp0out"
if not exist "%JH_OUT%" mkdir "%JH_OUT%"
python -I jh.py collect >> "%JH_OUT%\run_log.txt" 2>&1
python -I jh.py today > "%JH_OUT%\today_console.txt" 2>&1
if /I "%1"=="open" start "" "%JH_OUT%\today.html"
