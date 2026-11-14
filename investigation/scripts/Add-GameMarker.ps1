#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$SessionPath=(Join-Path $PSScriptRoot '..\raw\continuous'),
    [ValidateSet('spike','recovery','note','measurement','context')][string]$Event='measurement',
    [ValidateSet('Range','Stockholm-unrated','Unknown')][string]$Context='Unknown',
    [Nullable[double]]$RttAverageMs,
    [Nullable[double]]$RttMaxMs,
    [Nullable[double]]$LossInPercent,
    [Nullable[double]]$LossOutPercent,
    [Nullable[DateTimeOffset]]$ObservedAt
)
$ErrorActionPreference='Stop'
if(Test-Path -LiteralPath (Join-Path $SessionPath 'active.json')){
    $active=Get-Content -LiteralPath (Join-Path $SessionPath 'active.json') -Raw|ConvertFrom-Json
    $SessionPath=Join-Path $SessionPath $active.run_name
}
if (-not (Test-Path -LiteralPath (Join-Path $SessionPath 'metadata.json'))) { throw 'Not a collector session directory.' }
$recorded=[DateTimeOffset]::Now
$observation=$recorded; if ($null -ne $ObservedAt) { $observation=$ObservedAt }
$metadata=Get-Content -LiteralPath (Join-Path $SessionPath 'metadata.json') -Raw|ConvertFrom-Json
if($metadata.schema -ge 3){
    if(Test-Path -LiteralPath (Join-Path $SessionPath 'DONE')){throw 'Monitor is already stopped.'}
    foreach($loss in @($LossInPercent,$LossOutPercent)){if($null -ne $loss -and ($loss -lt 0 -or $loss -gt 100)){throw 'Loss must be 0..100.'}}
    foreach($rtt in @($RttAverageMs,$RttMaxMs)){if($null -ne $rtt -and $rtt -lt 0){throw 'RTT cannot be negative.'}}
    $data=[ordered]@{event=$Event;source='user_transcription';observed_local=$observation.ToString('yyyy-MM-ddTHH:mm:ss.fffzzz');rtt_avg_ms=$RttAverageMs;rtt_max_ms=$RttMaxMs;loss_in_pct=$LossInPercent;loss_out_pct=$LossOutPercent}
    if($PSBoundParameters.ContainsKey('Context')){$data.context=$Context}
    $name=[Guid]::NewGuid().ToString('N').Substring(0,12); $temp=Join-Path $SessionPath "commands\$name.tmp"; $destination=Join-Path $SessionPath "commands\$name.json"
    [IO.File]::WriteAllText($temp,($data|ConvertTo-Json -Compress),[Text.UTF8Encoding]::new($false))
    [IO.File]::Move($temp,$destination)
    return
}
[pscustomobject]@{observed_local=$observation.ToString('o'); recorded_local=$recorded.ToString('o'); context=$Context; rtt_avg_ms=$RttAverageMs; rtt_max_ms=$RttMaxMs; loss_in_pct=$LossInPercent; loss_out_pct=$LossOutPercent; source='user_transcription'; clock_precision='user-supplied or entry time; not an automatic game reading'} |
    ConvertTo-Json -Compress | Add-Content -LiteralPath (Join-Path $SessionPath 'game-markers.jsonl') -Encoding UTF8
