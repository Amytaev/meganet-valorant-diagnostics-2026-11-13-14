#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Target,
    [Parameter(Mandatory=$true)][string]$OutputPath,
    [ValidateRange(1,20)][int]$MaxHops=16,
    [ValidateRange(1000,3000)][int]$TimeoutMs=1500
)
$ErrorActionPreference='Stop'
$address=$null
if(-not [Net.IPAddress]::TryParse($Target,[ref]$address) -or $address.AddressFamily -ne 'InterNetwork'){throw 'Literal IPv4 required.'}
$ping=New-Object Net.NetworkInformation.Ping
$buffer=New-Object byte[] 32
try {
    for($ttl=1;$ttl -le $MaxHops;$ttl++) {
        $sent=[DateTimeOffset]::Now; $timer=[Diagnostics.Stopwatch]::StartNew()
        $options=New-Object Net.NetworkInformation.PingOptions($ttl,$false)
        $reply=$ping.Send($address,$TimeoutMs,$buffer,$options)
        $elapsed=$timer.Elapsed.TotalMilliseconds
        # On non-success .NET may omit the router address and returns no usable RTT.
        # Wall elapsed is a response/timeout duration, not a certified hop RTT.
        [pscustomobject]@{sent_local=$sent.ToString('o');target=$Target;protocol='ICMPv4 TTL-limited';ttl=$ttl;status=$reply.Status.ToString();reply_address=if($reply.Address -and $reply.Status -ne 'TimedOut'){$reply.Address.ToString()}else{$null};api_rtt_ms=if($reply.Status -eq 'Success'){$reply.RoundtripTime}else{$null};response_wait_ms=$elapsed;timeout_ms=$TimeoutMs;note='One probe per TTL; no DNS. Non-success wall duration is not a measured hop RTT; missing address/status cannot establish forwarding loss.'} |
            ConvertTo-Json -Compress | Add-Content -Encoding utf8 -LiteralPath $OutputPath
        if($reply.Status -eq 'Success'){break}
        if($elapsed -lt 1000){Start-Sleep -Milliseconds ([int](1000-$elapsed))}
    }
} finally {$ping.Dispose()}
