"""Cooperative cancellation shared by a wrapper and its native search children."""
import os


class SearchCancelled(RuntimeError):
    pass


class CancelEvent:
    def __init__(self, name=None, create=False):
        self.name=name or os.environ.get('AMA_FEVER_CANCEL_EVENT')
        self.handle=None
        if os.name=='nt' and self.name:
            import ctypes
            from ctypes import wintypes
            api=ctypes.WinDLL('kernel32',use_last_error=True)
            api.CreateEventW.argtypes=(ctypes.c_void_p,wintypes.BOOL,wintypes.BOOL,wintypes.LPCWSTR)
            api.CreateEventW.restype=wintypes.HANDLE
            api.OpenEventW.argtypes=(wintypes.DWORD,wintypes.BOOL,wintypes.LPCWSTR)
            api.OpenEventW.restype=wintypes.HANDLE
            for method in ('SetEvent','ResetEvent','CloseHandle'):
                getattr(api,method).argtypes=(wintypes.HANDLE,)
            api.WaitForSingleObject.argtypes=(wintypes.HANDLE,wintypes.DWORD)
            self.api=api
            self.handle=(api.CreateEventW(None,True,False,self.name) if create
                         else api.OpenEventW(0x00100000,False,self.name))
            if not self.handle:raise ctypes.WinError(ctypes.get_last_error())

    def set(self):
        if self.handle:self.api.SetEvent(self.handle)

    def reset(self):
        if self.handle:self.api.ResetEvent(self.handle)

    def check(self):
        if self.handle and self.api.WaitForSingleObject(self.handle,0)==0:
            raise SearchCancelled('search cancelled')

    def close(self):
        if self.handle:self.api.CloseHandle(self.handle);self.handle=None
