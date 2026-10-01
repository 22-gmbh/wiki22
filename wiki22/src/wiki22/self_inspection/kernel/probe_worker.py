"""Child process. Runs only a caller-reviewed, hash-bound probe in a disposable copy.
Audit hooks are defense in depth, NOT an OS sandbox for hostile Python bytecode.
"""
from __future__ import annotations
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import time


def main() -> None:
    job=json.loads(sys.stdin.read())
    root=Path(job['root']).resolve(); work=Path(job['work']).resolve()
    if not root.is_dir() or not work.is_dir(): raise RuntimeError('INVALID_COPY')
    try:
        import resource
        cpu_seconds = min(20, max(1, int(job.get('cpu_seconds', 5))))
        resource.setrlimit(resource.RLIMIT_CPU,(cpu_seconds,cpu_seconds))
        resource.setrlimit(resource.RLIMIT_AS,(768*1024*1024,768*1024*1024))
        resource.setrlimit(resource.RLIMIT_FSIZE,(2*1024*1024,2*1024*1024))
    except ImportError:
        pass
    stdlib=Path(os.__file__).resolve().parent
    native_stdlib=Path(sys.executable).resolve().parent if os.name=='nt' else None
    counters={'NETWORK_CALLS':0,'MODEL_CALLS':0,'NETWORK_ATTEMPTS_BLOCKED':0,'PROCESS_ATTEMPTS_BLOCKED':0,
              'OUTSIDE_READS_BLOCKED':0,'SOURCE_WRITES_BLOCKED':0}
    reads=set(); executed=set(); executed_lines={}
    code_ids={}
    trace_targets=set(job.get('trace_targets', []))
    def inside(p,b):
        try:return p.is_relative_to(b)
        except (ValueError,TypeError):return False
    def audit(event,args):
        if event.startswith('socket.') or event in {'urllib.Request','http.client.connect'}:
            counters['NETWORK_ATTEMPTS_BLOCKED']+=1;raise PermissionError('NETWORK_FORBIDDEN')
        if event in {'subprocess.Popen','os.system','os.posix_spawn','os.posix_spawnp','os.fork','pty.spawn','ctypes.dlopen','ctypes.dlsym'}:
            counters['PROCESS_ATTEMPTS_BLOCKED']+=1;raise PermissionError('PROCESS_OR_NATIVE_LOADER_FORBIDDEN')
        if event=='open' and args and not isinstance(args[0],int):
            p=Path(os.fsdecode(args[0])).resolve()
            mode=args[1];flags=args[2] if len(args)>2 and isinstance(args[2],int) else 0
            writing=(isinstance(mode,str) and any(c in mode for c in 'wax+')) or bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
            if writing:
                if not inside(p,work):
                    counters['SOURCE_WRITES_BLOCKED']+=1;raise PermissionError('WRITE_OUTSIDE_SCRATCH')
            elif not (inside(p,root) or inside(p,work) or (inside(p,stdlib) and 'site-packages' not in p.parts) or
                      (native_stdlib is not None and p.parent==native_stdlib and p.suffix.lower() in {'.zip','.pyd','.dll'})):
                counters['OUTSIDE_READS_BLOCKED']+=1;raise PermissionError('READ_OUTSIDE_APPROVED_COPY')
            if inside(p,root):reads.add(p.relative_to(root).as_posix())
        if event in {'os.remove','os.rmdir','os.mkdir','os.rename','os.replace','os.symlink','os.link','os.chmod','os.truncate'}:
            for a in args[:2]:
                if isinstance(a,(str,bytes)):
                    p=Path(os.fsdecode(a)).resolve()
                    if not inside(p,work):
                        counters['SOURCE_WRITES_BLOCKED']+=1;raise PermissionError('MUTATION_OUTSIDE_SCRATCH')
    def profile(frame,event,arg):
        if event=='call':
            # All copied code paths are absolute and symlink-free. Avoid a filesystem
            # resolve for every stdlib call merely to collect coverage of project code.
            filename=frame.f_code.co_filename
            if filename.startswith(str(root)+os.sep) and '<' not in frame.f_code.co_qualname:
                code=frame.f_code
                if code not in code_ids:
                    code_ids[code]=Path(filename).relative_to(root).as_posix()+'::'+code.co_qualname
                executed.add(code_ids[code])
    def trace(frame,event,arg):
        filename=frame.f_code.co_filename
        if filename.startswith(str(root)+os.sep):
            code=frame.f_code
            if code not in code_ids:
                code_ids[code]=Path(filename).relative_to(root).as_posix()+'::'+code.co_qualname
            if trace_targets and code_ids[code] not in trace_targets:
                return None
            if event=='line':
                key=Path(filename).relative_to(root).as_posix()
                executed_lines.setdefault(key,set()).add(frame.f_lineno)
            return trace
        return None
    os.chdir(root)
    for base in reversed(job.get('import_roots',['.','src'])):
        p=(root/base).resolve()
        if not inside(p,root):raise RuntimeError('BAD_IMPORT_ROOT')
        sys.path.insert(0,str(p))
    os.environ['SELF001_PROBE_WORK']=str(work)
    sys.dont_write_bytecode=True
    sys.addaudithook(audit);sys.setprofile(profile);sys.settrace(trace)
    status='PASS';error=None
    t=time.perf_counter_ns()
    try:
        # Drop arbitrary stdout/stderr; even exception messages can carry secrets.
        with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
            path=(root/job['file']).resolve()
            if not inside(path,root):raise RuntimeError('PROBE_PATH_ESCAPE')
            spec=importlib.util.spec_from_file_location('_self001_reviewed_probe',path)
            if spec is None or spec.loader is None:raise RuntimeError('MISSING_LOADER')
            mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
            fn=getattr(mod,job['function'])
            result=fn()
            if result is False:raise AssertionError('PROBE_RETURNED_FALSE')
    except BaseException as exc:
        status='FAIL';error=type(exc).__name__
    finally:sys.setprofile(None);sys.settrace(None)
    print(json.dumps({'status':status,'exception_type':error,'duration_ms':(time.perf_counter_ns()-t)/1e6,
                      'executed':sorted(executed),'executed_lines':{k:sorted(v) for k,v in sorted(executed_lines.items())},'read_files':sorted(reads),'audit':counters},sort_keys=True))

if __name__=='__main__': main()
