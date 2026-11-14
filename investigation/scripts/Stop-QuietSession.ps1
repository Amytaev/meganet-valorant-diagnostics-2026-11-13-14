#requires -Version 5.1
[CmdletBinding()]
param([string]$SessionPath=(Join-Path $PSScriptRoot '..\raw\continuous'),[switch]$NoAnalysis)
$ErrorActionPreference='Stop'
if(Test-Path -LiteralPath (Join-Path $SessionPath 'active.json')){
    $active=Get-Content -LiteralPath (Join-Path $SessionPath 'active.json') -Raw|ConvertFrom-Json
    $SessionPath=Join-Path $SessionPath $active.run_name
}
if (-not (Test-Path -LiteralPath (Join-Path $SessionPath 'metadata.json'))) { throw 'Not a collector session directory.' }
$metadata=Get-Content -LiteralPath (Join-Path $SessionPath 'metadata.json') -Raw|ConvertFrom-Json
if($metadata.schema -ge 3){
    $python=(Get-Command python.exe -ErrorAction Stop).Source
    & $python (Join-Path $PSScriptRoot 'continuous_monitor.py') stop --root $SessionPath
    if($LASTEXITCODE){throw 'Clean stop not confirmed; no force termination performed.'}
    if(-not $NoAnalysis){
        & $python (Join-Path $PSScriptRoot 'analyze_continuous.py') $SessionPath --report (Join-Path $SessionPath 'FINAL-RESULTS.md')
        if($LASTEXITCODE){throw 'Collector stopped; final analysis failed.'}
    }
    return
}
New-Item -ItemType File -Path (Join-Path $SessionPath 'STOP') -Force | Out-Null
