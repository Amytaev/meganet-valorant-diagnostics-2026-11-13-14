#requires -Version 5.1
$ErrorActionPreference='Stop'
$env:VALORANT_DIAG_WINDOWS_TESTS='1'
try{
 & (Get-Command python.exe -ErrorAction Stop).Source -m unittest discover -s $PSScriptRoot -p test_monitor_windows.py -v
 if($LASTEXITCODE){throw 'Continuous collector lifecycle test failed.'}
}finally{Remove-Item Env:\VALORANT_DIAG_WINDOWS_TESTS -ErrorAction SilentlyContinue}
