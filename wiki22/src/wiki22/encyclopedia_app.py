"""Loopback-only, offline encyclopedia interface for the existing Wiki22 corpus."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener
import webbrowser
from .encyclopedia_service import EncyclopediaService, bootstrap_registry, VERSION

ASSETS=Path(__file__).with_name('encyclopedia_web')


def choose_path(kind):
    """Native selector in its own process, isolated from HTTP worker threads."""
    if kind not in ('file','folder'):
        raise ValueError('Selettore non valido.')
    if os.name == 'nt':
        # Dialog type is validated above; paths are returned as JSON, never executed.
        dialog = 'FolderBrowserDialog' if kind == 'folder' else 'OpenFileDialog'
        prop = 'SelectedPath' if kind == 'folder' else 'FileName'
        script = ("[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); "
                  "Add-Type -AssemblyName System.Windows.Forms; "
                  f"$d = New-Object System.Windows.Forms.{dialog}; "
                  f"if ($d.ShowDialog() -eq 'OK') {{ @{{path=$d.{prop}}} | ConvertTo-Json -Compress }} "
                  "else { @{path=''} | ConvertTo-Json -Compress }")
        program = Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32/WindowsPowerShell/v1.0/powershell.exe'
        result = subprocess.run([str(program), '-NoProfile', '-STA', '-Command', script],
                                capture_output=True, encoding='utf-8', timeout=600)
        if result.returncode:
            raise ValueError('Il selettore non è disponibile. Incolla il percorso del file o della cartella.')
        return json.loads(result.stdout.lstrip('\ufeff'))
    script='''import json,sys,tkinter as tk
from tkinter import filedialog
root=tk.Tk();root.withdraw();root.attributes('-topmost',True)
try:
 path=filedialog.askdirectory(parent=root,title='Importa cartella in Wiki22') if sys.argv[1]=='folder' else filedialog.askopenfilename(parent=root,title='Importa file in Wiki22',filetypes=[('Testi e librerie','*.txt *.md *.json *.jsonl *.ndjson *.pdf *.epub *.docx *.odt *.fb2 *.html *.csv *.tsv *.pptx *.mobi *.azw *.azw3'),('Tutti i file','*')])
 print(json.dumps({'path':path},ensure_ascii=False))
finally:root.destroy()
'''
    result=subprocess.run([sys.executable,'-c',script,kind],capture_output=True,text=True,timeout=600)
    if result.returncode:
        raise ValueError('Il selettore non è disponibile. Incolla il percorso del file o della cartella.')
    return json.loads(result.stdout)


class EncyclopediaHTTP(ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=True

    def __init__(self, address, service):
        if address[0]!='127.0.0.1':
            raise ValueError('Wiki22 accetta soltanto connessioni locali.')
        self.service=service
        self.token=secrets.token_urlsafe(32)
        self.jobs={}
        self.exports={}
        self.jobs_lock=threading.Lock()
        self.worker=ThreadPoolExecutor(max_workers=1,thread_name_prefix='wiki22-import')
        super().__init__(address,Handler)

    def job(self, function, *args):
        with self.jobs_lock:
            self.jobs={k:v for k,v in self.jobs.items() if time.monotonic()-v['created']<3600}
            if sum(not j['future'].done() for j in self.jobs.values())>=2:
                raise ValueError('Attendi la conclusione dell’operazione in corso.')
            key=secrets.token_urlsafe(18)
            self.jobs[key]=dict(created=time.monotonic(),future=self.worker.submit(function,*args))
        return dict(job=key)

    def server_close(self):
        self.worker.shutdown(wait=True,cancel_futures=True)
        self.service.close()
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):
        pass

    def headers_ok(self, *, mutation=False):
        port=self.server.server_address[1]
        hosts={f'127.0.0.1:{port}',f'localhost:{port}'}
        if self.headers.get('Host') not in hosts:
            return False
        if mutation:
            origin=self.headers.get('Origin')
            if origin is not None and origin not in {'http://'+h for h in hosts}:
                return False
            return secrets.compare_digest(self.headers.get('X-Wiki22-Token',''),self.server.token)
        return True

    def send(self, status, body, content_type='application/json; charset=utf-8', attachment=False):
        if not isinstance(body,(bytes,bytearray)):
            body=json.dumps(body,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        if attachment:self.send_header('Content-Disposition','attachment; filename=Wiki22.html')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        self.end_headers()
        try:self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError):pass

    def do_GET(self):
        if not self.headers_ok():
            self.send(403,dict(error='Accesso locale non valido.'));return
        path=urlsplit(self.path).path
        if path.startswith('/download/'):
            with self.server.jobs_lock:export=self.server.exports.get(path.removeprefix('/download/'))
            if export and export.is_file():
                self.send(200,export.read_bytes(),'text/html; charset=utf-8',attachment=True);return
            self.send(404,dict(error='Esportazione non disponibile.'));return
        if path=='/api/health':
            self.send(200,dict(version=VERSION,root=str(self.server.service.root)));return
        assets={'/wiki22.svg':('wiki22.svg','image/svg+xml'),'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8')}
        if path in assets:
            filename,kind=assets[path]
            body=(ASSETS/filename).read_bytes()
            if filename=='index.html':body=body.replace(b'__WIKI22_TOKEN__',self.server.token.encode())
            self.send(200,body,kind);return
        self.send(404,dict(error='Pagina non disponibile.'))

    def do_POST(self):
        if not self.headers_ok(mutation=True):
            self.send(403,dict(error='Sessione non valida. Riapri Wiki22.'));return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=65536:raise ValueError('Richiesta troppo grande o vuota.')
            if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('Formato richiesta non valido.')
            value=json.loads(self.rfile.read(length))
            if not isinstance(value,dict):raise ValueError('Richiesta non valida.')
            path=urlsplit(self.path).path;s=self.server.service
            if path=='/api/shutdown':
                self.send(200,dict(stopping=True))
                threading.Thread(target=self.server.shutdown,daemon=True).start()
                return
            if path=='/api/bootstrap':result=dict(version=VERSION,libraries=s.libraries(),preferences=s.preferences(),shelf=s.shelf())
            elif path=='/api/library/manage':
                from .encyclopedia_management import manage
                result=manage(s,**value)
            elif path=='/api/places/resolve':
                from .encyclopedia_management import place_readings
                result=place_readings(s,**value)
            elif path=='/api/search':result=s.search(**value)
            elif path=='/api/suggest':result=s.suggest(**value)
            elif path=='/api/article':result=s.article(**value)
            elif path=='/api/compare':result=s.compare(**value)
            elif path=='/api/timeline':result=s.timeline(**value)
            elif path=='/api/timeline/date':result=s.timeline_date(**value)
            elif path=='/api/explore':
                from .encyclopedia_explore import catalog
                result=catalog()
            elif path=='/api/explore/resolve':result=s.explore(**value)
            elif path=='/api/formats':
                from .document_import import formats
                result=formats()
            elif path in ('/api/graph','/api/memory','/api/observe','/api/reason','/api/diagnose'):
                from . import encyclopedia_intelligence as intelligence
                operation=getattr(intelligence,path.rsplit('/',1)[1])
                result=self.server.job(lambda:operation(s,**value))
            elif path=='/api/preferences':result=s.save_preferences(value)
            elif path=='/api/shelf':result=s.shelf()
            elif path=='/api/shelf/remove':result=s.shelf_remove(**value)
            elif path=='/api/shelf/restore':result=s.shelf_restore(**value)
            elif path=='/api/research':result=s.research(**value)
            elif path=='/api/research/list':result=s.research_list()
            elif path=='/api/research/save':result=s.research_save(**value)
            elif path=='/api/research/open':result=s.research_open(**value)
            elif path=='/api/bookmark':result=s.bookmark(**value)
            elif path in ('/api/export','/api/research/export'):
                document=s.research_export(**value) if path=='/api/research/export' else s.export(**value)
                key=secrets.token_urlsafe(24)
                folder=s.state_dir/'exports';folder.mkdir(exist_ok=True)
                exported=folder/(time.strftime('%Y%m%d-%H%M%S')+'-'+key+'.html')
                exported.write_text(document,encoding='utf-8')
                with self.server.jobs_lock:self.server.exports[key]=exported
                result=dict(path=str(exported),url='/download/'+key)
            elif path=='/api/pick':result=self.server.job(choose_path,value.get('kind'))
            elif path=='/api/import':result=self.server.job(s.import_library,value.get('path'),value.get('name'))
            elif path=='/api/job':
                with self.server.jobs_lock:job=self.server.jobs.get(value.get('job'))
                if not job:raise ValueError('Operazione non disponibile.')
                if not job['future'].done():result=dict(status='RUNNING')
                else:result=dict(status='DONE',result=job['future'].result())
            else:self.send(404,dict(error='Operazione non disponibile.'));return
            self.send(200,result)
        except (ValueError,TypeError,KeyError,FileNotFoundError) as exc:
            self.send(400,dict(error=str(exc)))
        except Exception as exc:
            print('Wiki22 encyclopedia error:',repr(exc),file=sys.stderr,flush=True)
            self.send(500,dict(error='Non è stato possibile completare l’operazione. I dati originali sono conservati.'))


def default_root():
    repo=Path(__file__).resolve().parents[3]
    roots=[repo/'wiki22']
    installed=repo/'evidence/dialogue022/LOCAL_INSTALL001.json'
    if installed.is_file():
        candidate=Path(json.loads(installed.read_text())['new_package'])/'wiki22'
        if candidate.is_dir():roots.append(candidate)
    target=repo/'wiki22/.runtime/encyclopedia054/libraries'
    bootstrap_registry(target,roots)
    return target


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path)
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    root=args.root.resolve() if args.root else default_root()
    state=root/'.runtime';state.mkdir(parents=True,exist_ok=True)
    record=state/'encyclopedia-server.json'
    if record.is_file():
        try:
            prior=json.loads(record.read_text());port=int(prior['port'])
            if not 1<=port<=65535:raise ValueError('Invalid port')
            url=f'http://127.0.0.1:{port}/'
            opener=build_opener(ProxyHandler({}))
            with opener.open(url+'api/health',timeout=1) as response:health=json.load(response)
            if health==dict(version=VERSION,root=str(root)):
                if not args.no_browser:webbrowser.open(url)
                print(url,flush=True);return 0
        except Exception:pass
    service=EncyclopediaService(root)
    try:server=EncyclopediaHTTP(('127.0.0.1',args.port),service)
    except OSError:server=EncyclopediaHTTP(('127.0.0.1',0),service)
    port=server.server_address[1];url=f'http://127.0.0.1:{port}/'
    record.write_text(json.dumps(dict(port=port,pid=os.getpid(),version=VERSION)))
    print(url,flush=True)
    if not args.no_browser:webbrowser.open(url)
    try:server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:pass
    finally:server.server_close()
    return 0


if __name__=='__main__':raise SystemExit(main())
