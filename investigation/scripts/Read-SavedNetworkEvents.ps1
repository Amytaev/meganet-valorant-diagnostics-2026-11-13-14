#requires -Version 5.1
param(
    [datetime]$StartUtc=([datetime]::SpecifyKind([datetime]'2026-11-12 19:00:00',[DateTimeKind]::Utc)),
    [datetime]$EndUtc=([datetime]::UtcNow),
    [Parameter(Mandatory=$true)][string]$OutputPath
)
$ErrorActionPreference='Stop'
# Read existing event records only. No log enablement, settings, network tests or elevation.
function Event-Row($event){
    $codes=@{}
    try {
        [xml]$xml=$event.ToXml()
        foreach($data in $xml.Event.EventData.Data){
            if([string]$data.Name -match '^(ReasonCode|FailureReason|StatusCode|Reason|Status)$'){
                $value=0L
                if([long]::TryParse([string]$data.'#text',[ref]$value)){$codes[[string]$data.Name]=$value}
            }
        }
    }catch{}
    [ordered]@{time_utc=$event.TimeCreated.ToUniversalTime().ToString('o');event_id=$event.Id;level=$event.Level;provider=$event.ProviderName;numeric_codes=$codes}
}
$groups=@()
foreach($log in @('Microsoft-Windows-WLAN-AutoConfig/Operational','System')){
    $entry=[ordered]@{log=$log;start_utc=$StartUtc.ToUniversalTime().ToString('o');end_utc=$EndUtc.ToUniversalTime().ToString('o');enabled=$null;state='unknown';events=@()}
    try{
        $info=Get-WinEvent -ListLog $log -ErrorAction Stop
        $entry.enabled=$info.IsEnabled
        # Native event filters can interpret DateTime kinds differently. Read a
        # bounded padded interval and enforce exact UTC bounds on returned records.
        $filter=@{LogName=$log;StartTime=$StartUtc.ToLocalTime().AddDays(-1);EndTime=$EndUtc.ToLocalTime().AddDays(1)}
        if($log -eq 'System'){$filter.Level=@(1,2,3)}
        $events=@(Get-WinEvent -FilterHashtable $filter -ErrorAction Stop)
        $events=@($events|Where-Object {$_.TimeCreated.ToUniversalTime() -ge $StartUtc.ToUniversalTime() -and $_.TimeCreated.ToUniversalTime() -le $EndUtc.ToUniversalTime()})
        if($log -eq 'System'){
            $events=@($events|Where-Object {$_.ProviderName -match '^(Microsoft-Windows-(NDIS|WLAN-AutoConfig|TCPIP|DNS-Client|Kernel-PnP)|Tcpip|rtwlane\w*|rt640\w*|Netwtw\w*)$'})
        }
        $entry.events=@($events|ForEach-Object {Event-Row $_})
        $entry.state=if($entry.events.Count){'events_found'}else{'no_matching_events'}
    }catch{
        $entry.state=if($_.FullyQualifiedErrorId -match 'NoMatchingEventsFound'){'no_matching_events'}else{'query_error'}
        if($entry.state -eq 'query_error'){$entry.error_type=$_.Exception.GetType().FullName}
    }
    $groups+=$entry
}
[ordered]@{queried_utc=[DateTime]::UtcNow.ToString('o');method='read existing event logs; no rendered messages, computer/account names, SSID, MAC or GUID exported';groups=$groups}|
    ConvertTo-Json -Depth 9|Set-Content -LiteralPath $OutputPath -Encoding UTF8
$groups|ForEach-Object { '{0}: {1}, events={2}' -f $_.log,$_.state,$_.events.Count }
