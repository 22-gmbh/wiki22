from __future__ import annotations
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from .common import digest


class ProbeLedger:
    """Only receipts produced in this controller session are trusted automatically.
    Loading an arbitrary old JSON report never grants verified capability state.
    """
    def __init__(self):
        self._receipts={}
    def register(self, receipt: dict):
        key='PR-'+digest(receipt)[:24]
        self._receipts[key]=receipt
        return key
    def get(self,key):return self._receipts.get(key)
    def all(self):return dict(self._receipts)


def run_probe(root: Path, scan: dict, spec: dict, approved_hashes: dict[str,str], ledger: ProbeLedger) -> tuple[str,dict]:
    """Explicit consent is the reviewed allowlist, not names or discovered test presence.
    No .env, symlinks or arbitrary external data are copied to the child.
    """
    root=root.resolve()
    bound={**scan['inputs']['sorgenti'],**scan['inputs']['metadata']}
    bound.update({k:v['sha256'] for k,v in scan['inputs']['configurazioni'].items() if v['presente']})
    selected=spec['files']
    for rel in selected:
        p=root/rel
        if p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(root):raise ValueError('UNSAFE_PROBE_INPUT')
        expected=approved_hashes.get(rel)
        if expected is None or digest(p.read_bytes())!=expected:raise ValueError('PROBE_INPUT_NOT_REVIEWED_OR_CHANGED')
    # All executable dependencies in this exact probe copy are explicitly hashed.
    external=spec.get('external_probe')
    if external:
        external=Path(external).resolve()
        if not external.is_file() or digest(external.read_bytes())!=approved_hashes.get(spec['file']):raise ValueError('EXTERNAL_PROBE_NOT_REVIEWED')
    elif spec['file'] not in selected:raise ValueError('PROBE_FILE_NOT_APPROVED')
    with tempfile.TemporaryDirectory(prefix='ai22_self001_probe_') as td:
        base=Path(td);tree=base/'tree';work=base/'work';tree.mkdir();work.mkdir()
        for rel in selected:
            dest=tree/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((root/rel).read_bytes())
        if external:
            dest=tree/spec['file'];dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(external.read_bytes())
        env={k:os.environ[k] for k in ('SYSTEMROOT','WINDIR') if k in os.environ}
        env.update({'PYTHONDONTWRITEBYTECODE':'1','PYTHONIOENCODING':'utf-8','LANG':'C.UTF-8'})
        job={**spec,'root':str(tree),'work':str(work)}
        try:
            proc=subprocess.run([sys.executable,'-X','utf8','-I','-B',str(Path(__file__).with_name('probe_worker.py'))],
                                input=__import__('json').dumps(job),text=True,encoding='utf-8',capture_output=True,
                                timeout=spec.get('timeout',4),env=env,cwd=work)
            if proc.returncode!=0:
                result={'status':'FAIL','exception_type':'CHILD_PROCESS_ERROR','duration_ms':None,'executed':[],
                        'read_files':[],'audit':{}}
            else:
                result=__import__('json').loads(proc.stdout)
        except subprocess.TimeoutExpired:
            result={'status':'TIMEOUT','exception_type':'TimeoutExpired','duration_ms':None,'executed':[],
                    'read_files':[],'audit':{}}
        # No stdout or traceback from inspected code is ever copied to evidence.
    evidence={k:v for k,v in result.items() if k!='duration_ms'}
    evidence.update({'probe_id':spec['id'],'probe_source_hash':approved_hashes[spec['file']],
                     'probe_file':spec['file'],'tree_sha256':scan['tree_sha256'],
                     'source_hashes':{r:approved_hashes[r] for r in sorted(set(selected+[spec['file']]))},
                     'targets':spec['targets'],'timeout_seconds':spec.get('timeout',4),
                     'binding':'SOURCE_TREE_CONFIG_AND_REVIEWED_TEST_HASH',
                     'test_function':spec['function'], 'expected_result_not_in_scanner':True})
    key=ledger.register(evidence)
    return key,{'id':key,**evidence,'duration_ms':result['duration_ms']}
