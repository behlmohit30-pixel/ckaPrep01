@echo off
rem Wrapper: "jh today", "jh decide 4475988763 approve", ... Uses the Drive-synced JobHunt folders when present.
set "JH=D:\MoBe docs\CareerIreland\JobHunt"
if exist "%JH%\v3_private\profile.json" (
  set "JH_PRIVATE=%JH%\v3_private"
  set "JH_STATE=%JH%\v3_state"
  set "JH_OUT=%JH%\v3_out"
)
python -I "%~dp0jh.py" %*
