#requires -Version 5.1
[CmdletBinding()]
param(
    [string]$LogPath=(Join-Path $env:LOCALAPPDATA 'VALORANT\Saved\Logs\ShooterGame.log'),
    [Parameter(Mandatory=$true)][string]$OutputPath
)
$ErrorActionPreference='Stop'
# Never copy raw game logs: allowlist only timestamps, IP:port and log category.
# These are historical candidates, never automatically verified active UDP peers.
$info=Get-Item -LiteralPath $LogPath
if ($info.Length -gt 64MB) { throw 'Log exceeds bounded 64 MiB read limit.' }
$captured=[DateTimeOffset]::Now.ToString('o')
$rows=@(Get-Content -LiteralPath $LogPath -Tail 100000 | ForEach-Object {
    $line=$_
    $category=[regex]::Match($line,'\bLog[A-Za-z0-9_]+:').Value
    foreach ($m in [regex]::Matches($line,'(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}:\d{1,5}(?!\d)')) {
        $ip=$null; $parts=$m.Value.Split(':')
        if ([Net.IPAddress]::TryParse($parts[0],[ref]$ip) -and [int]$parts[1] -le 65535) {
            [pscustomobject]@{observed_local=$captured; log_time=[regex]::Match($line,'\[\d{4}\.\d{2}\.\d{2}[^\]]*\]').Value; category=$category; endpoint=$m.Value; active_game_udp_verified=$false}
        }
    }
})
[pscustomobject]@{observed_local=$captured; source_bytes=$info.Length; source_last_write=$info.LastWriteTime.ToString('o'); scan_limit_lines=100000; log_timezone='unverified'; candidates=$rows; note='Allowlisted extraction only. No candidate is proof of currently active game peer, transport or server region.'} |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $OutputPath -Encoding UTF8
