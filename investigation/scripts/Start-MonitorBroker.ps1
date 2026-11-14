#requires -Version 5.1
param([Parameter(Mandatory=$true)][string]$CommandLine,[Parameter(Mandatory=$true)][string]$WorkingDirectory)
$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
$startup=New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ShowWindow=[uint16]0;CreateFlags=[uint32](0x01000000 -bor 0x8 -bor 0x4000)}
$created=Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine=$CommandLine;CurrentDirectory=$WorkingDirectory;ProcessStartupInformation=$startup}
if($created.ReturnValue -ne 0){throw "Win32_Process.Create return code $($created.ReturnValue)"}
$process=Get-CimInstance Win32_Process -Filter "ProcessId=$($created.ProcessId)"
$parent=Get-CimInstance Win32_Process -Filter "ProcessId=$($process.ParentProcessId)"
if($parent.Name -ne 'WmiPrvSE.exe'){throw 'Independent WMI parent could not be verified.'}
[Console]::Out.Write(([pscustomobject]@{pid=$created.ProcessId;parent_pid=$process.ParentProcessId;parent_name=$parent.Name;launch_method='wmi-broker'}|ConvertTo-Json -Compress))
