"""Reference-counted offline guard for overlapping local workers."""
from __future__ import annotations
import socket
import threading
from contextlib import AbstractContextManager

class NetworkUnavailableError(RuntimeError):pass

_lock=threading.RLock()
_users=0
_originals=None
_NAMES=('socket','create_connection','getaddrinfo','gethostbyname','gethostbyname_ex')

class OfflineGuard(AbstractContextManager):
    """Keep network blocked until the last nested/concurrent guard exits."""
    def __enter__(self):
        global _users,_originals
        with _lock:
            if _users==0:
                _originals={name:getattr(socket,name) for name in _NAMES}
                class BlockedSocket(_originals['socket']):
                    def connect(self,*args,**kwargs):raise NetworkUnavailableError('Wiki22 offline guard: socket connect blocked')
                    def connect_ex(self,*args,**kwargs):raise NetworkUnavailableError('Wiki22 offline guard: socket connect_ex blocked')
                def blocked(*args,**kwargs):raise NetworkUnavailableError('Wiki22 offline guard: DNS/network connection blocked')
                socket.socket=BlockedSocket
                for name in _NAMES[1:]:setattr(socket,name,blocked)
            _users+=1
            self._depth=getattr(self,'_depth',0)+1
        return self
    def __exit__(self,*args):
        global _users,_originals
        with _lock:
            if not getattr(self,'_depth',0):raise RuntimeError('Offline guard exited without entry')
            self._depth-=1;_users-=1
            if _users==0:
                for name,value in _originals.items():setattr(socket,name,value)
                _originals=None
        return False
