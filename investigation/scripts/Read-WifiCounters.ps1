#requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][Guid]$InterfaceGuid,
    [Parameter(Mandatory=$true)][string]$OutputPath
)
$ErrorActionPreference='Stop'
# Query only: no WlanSetInterface, scans, monitor mode or frame capture.
# Structures and opcode follow the Microsoft WLAN_STATISTICS / PHY documentation.
if (-not ('QuietWlan.Native' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace QuietWlan {
    [StructLayout(LayoutKind.Sequential, Pack=8)]
    public struct Mac {
        public ulong Tx, Rx, WepExcluded, TkipMic, TkipReplays, TkipIcv, CcmpReplays, CcmpDecrypt, WepUndecryptable, WepIcv, DecryptSuccess, DecryptFailure;
    }
    [StructLayout(LayoutKind.Sequential, Pack=8)]
    public struct Header {
        public ulong FourWayHandshakeFailures, TkipCountermeasures, Reserved;
        public Mac Unicast, Multicast;
        public uint NumberOfPhys;
    }
    [StructLayout(LayoutKind.Sequential, Pack=8)]
    public struct Phy {
        public ulong TransmittedFrameCount, MulticastTransmittedFrameCount, FailedCount, RetryCount, MultipleRetryCount, MaxTxLifetimeExceededCount, TransmittedFragmentCount, RtsSuccessCount, RtsFailureCount, AckFailureCount, ReceivedFrameCount, MulticastReceivedFrameCount, PromiscuousReceivedFrameCount, MaxRxLifetimeExceededCount, FrameDuplicateCount, ReceivedFragmentCount, PromiscuousReceivedFragmentCount, FcsErrorCount;
    }
    public class Result {
        public uint OpenStatus, QueryStatus, Bytes;
        public string Stage;
        public Header Header;
        public Phy[] Phys;
    }
    public static class Native {
        [DllImport("wlanapi.dll")] static extern uint WlanOpenHandle(uint version, IntPtr reserved, out uint negotiated, out IntPtr handle);
        [DllImport("wlanapi.dll")] static extern uint WlanQueryInterface(IntPtr handle, ref Guid guid, uint opcode, IntPtr reserved, out uint bytes, out IntPtr data, out uint valueType);
        [DllImport("wlanapi.dll")] static extern void WlanFreeMemory(IntPtr data);
        [DllImport("wlanapi.dll")] static extern uint WlanCloseHandle(IntPtr handle, IntPtr reserved);
        public static Result Read(Guid guid) {
            Result r=new Result(); IntPtr handle=IntPtr.Zero, data=IntPtr.Zero; uint version, kind;
            r.Stage="open"; r.OpenStatus=WlanOpenHandle(2,IntPtr.Zero,out version,out handle);
            if(r.OpenStatus!=0) return r;
            try {
                r.Stage="query";
                r.QueryStatus=WlanQueryInterface(handle,ref guid,0x10000101,IntPtr.Zero,out r.Bytes,out data,out kind);
                if(r.QueryStatus!=0) return r;
                int header=Marshal.SizeOf(typeof(Header)), phy=Marshal.SizeOf(typeof(Phy));
                if(header!=224 || phy!=144 || r.Bytes<header) throw new InvalidOperationException("Unexpected WLAN buffer layout.");
                r.Header=(Header)Marshal.PtrToStructure(data,typeof(Header));
                if(r.Header.NumberOfPhys>64 || r.Bytes<header+(long)r.Header.NumberOfPhys*phy) throw new InvalidOperationException("Truncated WLAN PHY array.");
                r.Phys=new Phy[r.Header.NumberOfPhys];
                for(int i=0;i<r.Phys.Length;i++) r.Phys[i]=(Phy)Marshal.PtrToStructure(IntPtr.Add(data,header+i*phy),typeof(Phy));
                r.Stage="complete"; return r;
            } finally { if(data!=IntPtr.Zero) WlanFreeMemory(data); WlanCloseHandle(handle,IntPtr.Zero); }
        }
    }
}
'@
}
$result=[QuietWlan.Native]::Read($InterfaceGuid)
[pscustomobject]@{local=[DateTimeOffset]::Now.ToString('o'); interface_guid=$InterfaceGuid; method='WlanQueryInterface statistics (read only)'; result=$result; note='Cumulative driver counters; compare deltas only, support and fidelity depend on driver. Not game packet loss.'} |
    ConvertTo-Json -Depth 7 -Compress | Add-Content -LiteralPath $OutputPath -Encoding UTF8
$result | Select-Object Stage,OpenStatus,QueryStatus,Bytes,Phys
