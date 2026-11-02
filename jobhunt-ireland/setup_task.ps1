# Registers two daily runs (09:00 and 17:00). StartWhenAvailable runs a missed slot as soon as the PC is back on,
# which fixes v2's problem (2 runs in 11 days because the PC was off at the scheduled time).
# Run once in PowerShell:  powershell -ExecutionPolicy Bypass -File .\setup_task.ps1
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$action = New-ScheduledTaskAction -Execute "$dir\run_daily.cmd" -WorkingDirectory $dir
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
foreach ($t in @("09:00", "17:00")) {
  $trigger = New-ScheduledTaskTrigger -Daily -At $t
  Register-ScheduledTask -TaskName "JobHunt v3 $($t.Replace(':',''))" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
  Write-Host "Registered JobHunt v3 at $t"
}
