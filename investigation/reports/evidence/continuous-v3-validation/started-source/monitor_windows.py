"""Read-only Windows APIs. No capture, keyboard hook, process memory or network changes."""
import ctypes as C
from ctypes import wintypes as W
import socket
import struct
import threading
import time
from datetime import datetime, timezone


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


class Options(C.Structure):
    _fields_=[('ttl',C.c_ubyte),('tos',C.c_ubyte),('flags',C.c_ubyte),('size',C.c_ubyte),('data',C.c_void_p)]


class Reply(C.Structure):
    _fields_=[('address',W.DWORD),('status',W.DWORD),('rtt',W.DWORD),('size',W.WORD),('reserved',W.WORD),('data',C.c_void_p),('options',Options)]


class Native:
    def __init__(self):
        self.kernel=C.WinDLL('kernel32',use_last_error=True)
        self.icmp=C.WinDLL('iphlpapi',use_last_error=True)
        self.kernel.GetCurrentProcess.restype=W.HANDLE
        self.kernel.IsProcessInJob.argtypes=[W.HANDLE,W.HANDLE,C.POINTER(W.BOOL)]
        self.kernel.CloseHandle.argtypes=[W.HANDLE]
        self.kernel.CreateMutexW.argtypes=[C.c_void_p,W.BOOL,W.LPCWSTR]
        self.kernel.CreateMutexW.restype=W.HANDLE
        self.icmp.IcmpCreateFile.restype=W.HANDLE
        self.icmp.IcmpCloseHandle.argtypes=[W.HANDLE]
        self.icmp.IcmpSendEcho2.argtypes=[W.HANDLE,W.HANDLE,C.c_void_p,C.c_void_p,W.DWORD,C.c_void_p,W.WORD,C.POINTER(Options),C.c_void_p,W.DWORD,W.DWORD]
        self.icmp.IcmpSendEcho2.restype=W.DWORD
        self.mutex=None

    def in_job(self):
        result=W.BOOL()
        if not self.kernel.IsProcessInJob(self.kernel.GetCurrentProcess(),None,C.byref(result)):
            raise C.WinError(C.get_last_error())
        return bool(result.value)

    def singleton(self):
        self.mutex=self.kernel.CreateMutexW(None,False,'Local\\ValorantNetDiag-Continuous-v3')
        if not self.mutex:
            raise C.WinError(C.get_last_error())
        if C.get_last_error()==183:
            self.kernel.CloseHandle(self.mutex); self.mutex=None
            raise RuntimeError('Another continuous monitor already owns the per-user mutex.')

    def close(self):
        if self.mutex:
            self.kernel.CloseHandle(self.mutex); self.mutex=None

    def desktop_info(self):
        user=C.WinDLL('user32',use_last_error=True)
        user.GetProcessWindowStation.restype=W.HANDLE
        user.GetThreadDesktop.argtypes=[W.DWORD]; user.GetThreadDesktop.restype=W.HANDLE
        user.GetUserObjectInformationW.argtypes=[W.HANDLE,C.c_int,C.c_void_p,W.DWORD,C.POINTER(W.DWORD)]
        def name(handle):
            value=C.create_unicode_buffer(256); needed=W.DWORD()
            if not user.GetUserObjectInformationW(handle,2,value,C.sizeof(value),C.byref(needed)):
                return 'unavailable'
            return value.value
        session=W.DWORD()
        self.kernel.ProcessIdToSessionId(self.kernel.GetCurrentProcessId(),C.byref(session))
        return dict(session_id=session.value,window_station=name(user.GetProcessWindowStation()),
                    desktop=name(user.GetThreadDesktop(self.kernel.GetCurrentThreadId())))

    def probe(self,target,timeout_ms,cycle,origin):
        sent=datetime.now(timezone.utc); mono=time.monotonic()
        row=dict(target=target,cycle=cycle,protocol='ICMPv4',sent_utc=sent.isoformat(timespec='milliseconds'),
                 sent_local=sent.astimezone().isoformat(timespec='milliseconds'),elapsed_ms=round((mono-origin)*1000,3),rtt_ms=None)
        handle=None
        try:
            handle=self.icmp.IcmpCreateFile()
            if handle in (None,C.c_void_p(-1).value):
                raise C.WinError(C.get_last_error())
            buffer=C.create_string_buffer(C.sizeof(Reply)+32+8+256)
            payload=C.create_string_buffer(b'V'*32,32)
            options=Options(128,0,0,0,None)
            count=self.icmp.IcmpSendEcho2(handle,None,None,None,struct.unpack('<I',socket.inet_aton(target))[0],payload,32,C.byref(options),buffer,len(buffer),timeout_ms)
            if count:
                reply=Reply.from_buffer(buffer); code=reply.status
                if code==0:
                    row['rtt_ms']=reply.rtt
            else:
                code=C.get_last_error()
            row['status']={0:'Success',11010:'TimedOut',11013:'TtlExpired',11002:'DestinationNetworkUnreachable',11003:'DestinationHostUnreachable'}.get(code,'ProbeError' if code<11000 else 'IPStatus'+str(code))
            row['native_status']=code
        except Exception as exc:
            row.update(status='ProbeError',error_type=type(exc).__name__)
        finally:
            if handle not in (None,C.c_void_p(-1).value):
                self.icmp.IcmpCloseHandle(handle)
        row['observed_wait_ms']=round((time.monotonic()-mono)*1000,3)
        row['completed_utc']=timestamp()
        row['quality']='early_timeout_unverified' if row['status']=='TimedOut' and row['observed_wait_ms']<timeout_ms-100 else 'normal'
        return row


class Controls:
    """Hidden top-level window receives only our hotkeys and OS session-end messages."""
    keys={1:('spike',0x77),2:('recovery',0x78),3:('note',0x79),4:('stop',0x7A)}

    def __init__(self,events,stop,finished,hotkeys=True):
        self.events=events; self.stop=stop; self.finished=finished; self.hotkeys=hotkeys
        self.ready=threading.Event(); self.available={}; self.error=None; self.hwnd=None
        self.thread=threading.Thread(target=self._loop,name='OS-controls',daemon=True)
        self.thread.start()
        if not self.ready.wait(5):
            raise RuntimeError('OS control window did not initialize.')
        if self.error:
            raise RuntimeError(self.error)

    def _loop(self):
        user=C.WinDLL('user32',use_last_error=True); kernel=C.WinDLL('kernel32',use_last_error=True)
        LRESULT=C.c_ssize_t; WPARAM=C.c_size_t; LPARAM=C.c_ssize_t
        PROC=C.WINFUNCTYPE(LRESULT,W.HWND,W.UINT,WPARAM,LPARAM)
        class WC(C.Structure):
            _fields_=[('style',W.UINT),('proc',PROC),('cls',C.c_int),('wnd',C.c_int),('instance',W.HINSTANCE),('icon',W.HANDLE),('cursor',W.HANDLE),('brush',W.HANDLE),('menu',W.LPCWSTR),('name',W.LPCWSTR)]
        user.DefWindowProcW.argtypes=[W.HWND,W.UINT,WPARAM,LPARAM]; user.DefWindowProcW.restype=LRESULT
        user.CreateWindowExW.argtypes=[W.DWORD,W.LPCWSTR,W.LPCWSTR,W.DWORD,C.c_int,C.c_int,C.c_int,C.c_int,W.HWND,W.HMENU,W.HINSTANCE,C.c_void_p]
        user.CreateWindowExW.restype=W.HWND
        user.RegisterHotKey.argtypes=[W.HWND,C.c_int,W.UINT,W.UINT]
        user.UnregisterHotKey.argtypes=[W.HWND,C.c_int]
        user.GetMessageW.argtypes=[C.POINTER(W.MSG),W.HWND,W.UINT,W.UINT]
        user.PostMessageW.argtypes=[W.HWND,W.UINT,WPARAM,LPARAM]
        user.DispatchMessageW.argtypes=[C.POINTER(W.MSG)]; user.DispatchMessageW.restype=LRESULT
        user.DestroyWindow.argtypes=[W.HWND]
        kernel.GetModuleHandleW.restype=W.HMODULE

        @PROC
        def callback(hwnd,msg,wparam,lparam):
            if msg==0x312:
                name=self.keys.get(wparam,('unknown',0))[0]
                self.events.put(dict(event=name,source='RegisterHotKey',observed_utc=timestamp()))
                if name=='stop':
                    self.stop.set()
                return 0
            if msg==0x11:  # Query end-session: allow, no veto or premature stop.
                return 1
            if msg==0x16 and wparam:
                self.events.put(dict(event='windows_session_end',source='WM_ENDSESSION',observed_utc=timestamp()))
                self.stop.set(); self.finished.wait(2)
                return 0
            if msg==0x10:
                user.DestroyWindow(hwnd); return 0
            if msg==0x2:
                user.PostQuitMessage(0); return 0
            return user.DefWindowProcW(hwnd,msg,wparam,lparam)
        try:
            name='ValorantNetDiagHiddenControls-'+str(threading.get_ident())
            instance=kernel.GetModuleHandleW(None)
            wc=WC(0,callback,0,0,instance,None,None,None,None,name)
            if not user.RegisterClassW(C.byref(wc)):
                raise C.WinError(C.get_last_error())
            # No WS_VISIBLE, no activation, no overlays, no input hooks.
            self.hwnd=user.CreateWindowExW(0x08000080,name,'',0,0,0,0,0,None,None,instance,None)
            if not self.hwnd:
                raise C.WinError(C.get_last_error())
            for ident,(event,key) in self.keys.items():
                self.available[event]=bool(user.RegisterHotKey(self.hwnd,ident,0x4000|1|2|4,key)) if self.hotkeys else False
            self.ready.set()
            msg=W.MSG()
            while user.GetMessageW(C.byref(msg),None,0,0)>0:
                user.TranslateMessage(C.byref(msg)); user.DispatchMessageW(C.byref(msg))
        except Exception as exc:
            self.error=type(exc).__name__+': '+str(exc); self.ready.set()
        finally:
            for ident in self.keys:
                if self.hwnd:
                    user.UnregisterHotKey(self.hwnd,ident)

    def close(self):
        if self.hwnd:
            C.WinDLL('user32').PostMessageW(W.HWND(self.hwnd),0x10,0,0)
        self.thread.join(timeout=1)
