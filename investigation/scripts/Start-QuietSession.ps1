#requires -Version 5.1
[CmdletBinding()]
param(
 [string]$OutputRoot=(Join-Path $PSScriptRoot '..\raw\continuous'),
 [ValidateRange(0,2147483647)][int]$DurationSeconds=0,
 [ValidateRange(1,30)][int]$IntervalSeconds=2,
 [ValidateRange(1000,3000)][int]$TimeoutMs=1500,
 [ValidateCount(1,5)][string[]]$Targets=@('192.168.123.1','89.38.164.205','1.1.1.1','87.245.238.34','87.245.233.166'),
 [ValidateSet('Range','Stockholm-unrated','Unknown')][string]$Context='Unknown',
 [ValidateRange(1,86400)][int]$RotateSeconds=900,
 [ValidateRange(1,10240)][int]$BudgetMiB=512,
 [switch]$SkipSystemSnapshot,[switch]$NoHotkeys
)
$ErrorActionPreference='Stop'
$python=(Get-Command python.exe -ErrorAction Stop).Source
$arguments=@((Join-Path $PSScriptRoot 'continuous_monitor.py'),'start','--root',$OutputRoot,'--duration',"$DurationSeconds",'--interval',"$IntervalSeconds",'--timeout',"$TimeoutMs",'--context',$Context,'--rotate-seconds',"$RotateSeconds",'--budget-mib',"$BudgetMiB",'--targets')+$Targets
if($SkipSystemSnapshot){$arguments+='--skip-system'}
if($NoHotkeys){$arguments+='--no-hotkeys'}
& $python @arguments
if($LASTEXITCODE){throw "Continuous launcher exited with code $LASTEXITCODE"}
