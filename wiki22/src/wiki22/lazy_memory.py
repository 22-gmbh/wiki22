"""Load native learned memory only for a query that actually uses it.

The frozen NativeSession remains unchanged. Source-field and documentary study
queries can complete without replaying unrelated personal observations.
"""
from pathlib import Path
import threading

class LazyNativeSession:
    def __init__(self,path,*,factory=None):
        self.path=Path(path);self._session=None;self._factory=factory;self._version=None
        self._closed=False;self._lock=threading.RLock()
    @property
    def loaded(self):return self._session is not None
    def _get(self):
        with self._lock:
            if self._closed:raise RuntimeError('Native memory session is closed')
            if self._session is None:
                factory=self._factory
                if factory is None:
                    from .native22_linguistic_guarded.session import NativeSession
                    factory=NativeSession
                self._session=factory(self.path)
                self._version=self._session.journal.execute('PRAGMA data_version').fetchone()[0]
            else:
                version=self._session.journal.execute('PRAGMA data_version').fetchone()[0]
                if version!=self._version:
                    self._session._replay()
                    self._version=version
            return self._session
    def __getattr__(self,name):
        if name.startswith('_'):raise AttributeError(name)
        return getattr(self._get(),name)
    def close(self):
        with self._lock:
            self._closed=True
            if self._session is not None:self._session.close();self._session=None
