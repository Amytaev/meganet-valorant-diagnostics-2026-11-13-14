#requires -Version 5.1
param([string]$TargetsJson='[]',[switch]$Inventory)
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
try{[Diagnostics.Process]::GetCurrentProcess().PriorityClass='BelowNormal'}catch{}
$result=[ordered]@{observed_local=[DateTimeOffset]::Now.ToString('o');errors=@()}
try{$result.counters=@(Get-NetAdapterStatistics|Select-Object Name,ReceivedBytes,SentBytes,ReceivedDiscardedPackets,OutboundDiscardedPackets,ReceivedPacketErrors,OutboundPacketErrors)}catch{$result.errors+='counters:'+ $_.Exception.GetType().Name}
try{$result.wlan=(& netsh wlan show interfaces 2>&1)-join "`n"}catch{$result.errors+='wlan:'+ $_.Exception.GetType().Name}
try{$ids=@(Get-Process -Name VALORANT-Win64-Shipping -ErrorAction SilentlyContinue|Select-Object -ExpandProperty Id);$result.game_pids=$ids;$result.udp_bindings=@();if($ids.Count){$result.udp_bindings=@(Get-NetUDPEndpoint|Where-Object{$ids -contains $_.OwningProcess}|Select-Object LocalAddress,LocalPort,OwningProcess)}}catch{$result.errors+='game-sockets:'+ $_.Exception.GetType().Name}
if($Inventory){
    try{$result.adapters=@(Get-NetAdapter|Select-Object Name,InterfaceDescription,ifIndex,Status,LinkSpeed,DriverVersion,DriverDate)}catch{$result.errors+='adapters:'+ $_.Exception.GetType().Name}
    try{$result.routes=@(Get-NetRoute|Select-Object InterfaceAlias,InterfaceIndex,AddressFamily,DestinationPrefix,NextHop,RouteMetric)}catch{$result.errors+='routes:'+ $_.Exception.GetType().Name}
    try{$result.selected_routes=@(foreach($t in ($TargetsJson|ConvertFrom-Json)){[pscustomobject]@{target=$t;selection=@(Find-NetRoute -RemoteIPAddress $t|Select-Object IPAddress,InterfaceAlias,InterfaceIndex,DestinationPrefix,NextHop,RouteMetric,InterfaceMetric)}})}catch{$result.errors+='selected-routes:'+ $_.Exception.GetType().Name}
}
[Console]::Out.Write(($result|ConvertTo-Json -Depth 7 -Compress))
