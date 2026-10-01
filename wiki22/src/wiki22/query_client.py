"""Bounded desktop transport to its own persistent local query child."""
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import threading
import time
from .query_worker import MAX_REQUEST_BYTES,MAX_RESPONSE_BYTES

class WarmQueryClient:
    def __init__(self,workspace_root,wiki22_root,*,timeout=90):
        self.workspace=Path(workspace_root);self.root=Path(wiki22_root)
        self.timeout=timeout;self.process=None;self.lock=threading.Lock();self.serial=0;self.closed=False

    def _start(self):
        if self.closed:raise RuntimeError('Local query client is closed')
        env=dict(os.environ,PYTHONPATH=str(self.root/'src'),PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',PYTHONUTF8='1')
        command=[sys.executable,'-u','-m','wiki22.query_worker','--workspace-root',str(self.workspace),'--wiki22-root',str(self.root)]
        self.process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,cwd=self.workspace,bufsize=0)

    def _stop(self):
        process=self.process;self.process=None
        if process is None:return
        if process.poll() is None:
            if process.stdin:process.stdin.close()
            try:process.wait(timeout=1)
            except subprocess.TimeoutExpired:pass
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
        for stream in [process.stdin,process.stdout,process.stderr]:
            if stream:stream.close()

    def close(self):
        self.closed=True;self._stop()

    def warmup(self):
        return self._exchange(dict(operation='warmup'))

    def query(self,query,scope_env):
        return self._exchange(dict(query=' '.join(query.splitlines()),scope=dict(
            mode=scope_env.get('WIKI22_SCOPE_MODE',''),
            library_ids=[x.strip() for x in scope_env.get('WIKI22_SCOPE_LIBRARIES','').split(',') if x.strip()])))

    def _exchange(self,request):
        with self.lock:
            self.serial+=1
            request=dict(request,request_id=self.serial)
            payload=json.dumps(request,ensure_ascii=False,separators=(',',':')).encode()+b'\n'
            if len(payload)>MAX_REQUEST_BYTES:raise ValueError('Question exceeds local protocol budget')
            try:
                if self.process is None or self.process.poll() is not None:
                    self._stop();self._start()
                process=self.process;process.stdin.write(payload);process.stdin.flush()
                deadline=time.monotonic()+self.timeout;body=bytearray();errors=bytearray()
                with selectors.DefaultSelector() as selector:
                    selector.register(process.stdout,selectors.EVENT_READ,'out');selector.register(process.stderr,selectors.EVENT_READ,'err')
                    while b'\n' not in body:
                        remaining=deadline-time.monotonic()
                        if remaining<=0:raise subprocess.TimeoutExpired('Wiki22 local query worker',self.timeout)
                        ready=selector.select(remaining)
                        if not ready:raise subprocess.TimeoutExpired('Wiki22 local query worker',self.timeout)
                        for key,_ in ready:
                            chunk=os.read(key.fileobj.fileno(),65536)
                            if not chunk:
                                selector.unregister(key.fileobj)
                                if key.data=='out':raise RuntimeError('Local query process stopped: '+errors.decode(errors='replace')[:500])
                                continue
                            target=body if key.data=='out' else errors;target.extend(chunk)
                            if len(target)>(MAX_RESPONSE_BYTES if key.data=='out' else 65536):raise ValueError('Local query response exceeded its budget')
                if not body.endswith(b'\n') or body.count(b'\n')!=1:raise ValueError('Unexpected local response framing')
                response=json.loads(body)
                if response.get('request_id')!=self.serial:raise ValueError('Local response identity mismatch')
                if not response.get('ok'):raise RuntimeError(response.get('error','Local query failed'))
                return response
            except Exception:
                self._stop();raise
