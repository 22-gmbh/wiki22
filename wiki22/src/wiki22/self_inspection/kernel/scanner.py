from __future__ import annotations
import ast
import io
from importlib.machinery import PathFinder
import json
import os
import re
import sys
import tokenize
import tomllib
from pathlib import Path
from typing import Any
from .common import SENSITIVE, digest, label

EXCLUDE_DIRS = {'.git', '.venv', 'venv', '__pycache__', 'node_modules', 'evidence', 'evidenze',
                'portable-runtime', 'real_inputs', 'fixture_templates', 'artifacts', 'outputs', '.runs', '.ssh', 'browser_profiles', 'private'}
META_FILES = {'pyproject.toml', 'PACKAGE_MANIFEST.json', 'DELIVERY_MANIFEST.json', 'SOURCE_MANIFEST.json', 'self001_config.json'}


class ScopeError(RuntimeError):
    pass


def authorized_root(path: Path, allowed: list[Path]) -> Path:
    if path.is_symlink():
        raise ScopeError('RADICE_SIMBOLICA_NON_AMMESSA')
    root = path.resolve(strict=True)
    if root not in [p.resolve(strict=True) for p in allowed]:
        raise ScopeError('RADICE_NON_AUTORIZZATA')
    if root == Path(root.anchor) or root == Path.home().resolve() or root.as_posix() in {'/home', '/etc', '/run/media', '/mnt/data'}:
        raise ScopeError('RADICE_TROPPO_AMPIA')
    if not root.is_dir():
        raise ScopeError('RADICE_NON_DIRECTORY')
    return root


def source_text(raw: bytes) -> str:
    encoding, _ = tokenize.detect_encoding(io.BytesIO(raw).readline)
    return raw.decode(encoding, errors='strict')


def call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name): return node.id
    if isinstance(node, ast.Attribute): return call_name(node.value) + '.' + node.attr
    return '<espressione>'


def signature(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> dict:
    """Never expose default values or literal/string annotations."""
    def ann(a):
        return label(a.id) if isinstance(a, ast.Name) else ('TIPO_STRUTTURATO' if a is not None else None)
    args = [{'nome': label(a.arg), 'tipo': ann(a.annotation), 'modo': kind}
            for kind, group in [('posizionale_solo', fn.args.posonlyargs), ('posizionale', fn.args.args), ('keyword_solo', fn.args.kwonlyargs)]
            for a in group]
    for kind, a in [('varargs', fn.args.vararg), ('kwargs', fn.args.kwarg)]:
        if a: args.append({'nome': label(a.arg), 'tipo': ann(a.annotation), 'modo': kind})
    return {'parametri': args, 'default_count': len(fn.args.defaults) + sum(x is not None for x in fn.args.kw_defaults),
            'ritorno': ann(fn.returns), 'async': isinstance(fn, ast.AsyncFunctionDef)}


def imports(tree: ast.Module, rel: str) -> list[dict]:
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append({'modulo': label(alias.name), 'simboli': [], 'alias': label(alias.asname or alias.name.split('.')[0]),
                            'livello': 0, 'linea': node.lineno})
        elif isinstance(node, ast.ImportFrom):
            out.append({'modulo': label(node.module or ''), 'simboli': [label(a.name) for a in node.names],
                        'alias': None, 'livello': node.level, 'linea': node.lineno})
    return sorted(out, key=lambda x: (x['linea'], x['modulo']))


def structural_facts(fn: ast.AST) -> dict:
    """AST motifs, not a marketing/name-to-capability lookup. Intentionally bounded."""
    body = [x for x in fn.body if not (isinstance(x, ast.Expr) and isinstance(x.value, ast.Constant) and isinstance(x.value.value, str))]
    meaningful = body and not all(isinstance(x, ast.Pass) or (isinstance(x, ast.Expr) and isinstance(x.value, ast.Constant))
                                 or (isinstance(x, ast.Raise) and 'NotImplemented' in call_name(x.exc.func if isinstance(x.exc, ast.Call) else x.exc))
                                 for x in body)
    nodes = list(ast.walk(fn))
    calls = sorted({call_name(x.func) for x in nodes if isinstance(x, ast.Call)})
    strings = {x.value for x in nodes if isinstance(x, ast.Constant) and isinstance(x.value, str) and len(x.value) < 120}
    motifs = []
    returns = any(isinstance(x, (ast.Return, ast.Yield, ast.YieldFrom)) for x in nodes)
    if meaningful:
        if any(c.endswith(('.read_text', '.read_bytes')) for c in calls): motifs.append('lettura_file_locale')
        if any(c.endswith(('.write_text', '.write_bytes')) for c in calls): motifs.append('scrittura_file_locale')
        if any(c.endswith(('.finditer', '.findall')) for c in calls) and returns: motifs.append('segmentazione_testuale')
        if any(c.endswith(('.casefold', '.lower')) for c in calls) and returns: motifs.append('normalizzazione_testuale')
        if (any(isinstance(x, (ast.ListComp, ast.GeneratorExp, ast.For)) for x in nodes)
                and any(isinstance(x, ast.Compare) and any(isinstance(o, ast.In) for o in x.ops) for x in nodes)
                and any(c.endswith(('.casefold', '.lower')) for c in calls) and returns): motifs.append('ricerca_testuale_locale')
        if any(c in {'json.dumps', 'json.dump'} for c in calls): motifs.append('serializzazione_json')
        if any(c.endswith('.sha256') for c in calls): motifs.append('impronta_crittografica')
        if 'ast.parse' in calls: motifs.append('ispezione_sorgenti_python')
        if any(isinstance(x, ast.Assign) and any(isinstance(t, (ast.Subscript, ast.Attribute)) for t in x.targets) for x in nodes):
            motifs.append('aggiornamento_stato_locale')
        if any(c.endswith('.get') for c in calls) and returns: motifs.append('consultazione_struttura_dati')
        if 'sys.addaudithook' in calls and any(isinstance(x, ast.Raise) for x in nodes): motifs.append('controllo_accessi_runtime')
        if any(c.startswith(('socket.', 'urllib.', 'requests.', 'http.')) for c in calls): motifs.append('accesso_rete')
        if returns and not motifs and any(isinstance(x, (ast.BinOp, ast.Compare, ast.Call, ast.Subscript)) for x in nodes):
            motifs.append('elaborazione_dati')
    # A JSON filename is NOT automatically a configuration dependency. Only
    # literals on an actual read/open-for-read expression qualify in this kernel.
    config=set()
    for n in nodes:
        if not isinstance(n,ast.Call):continue
        name=call_name(n.func)
        readable=name.endswith(('.read_text','.read_bytes'))
        if name=='open':
            mode=n.args[1] if len(n.args)>1 else None
            readable=mode is None or (isinstance(mode,ast.Constant) and isinstance(mode.value,str) and not any(c in mode.value for c in 'wax+'))
        if not readable:continue
        receiver=n.func.value if isinstance(n.func,ast.Attribute) else n
        for x in ast.walk(receiver):
            if isinstance(x,ast.Constant) and isinstance(x.value,str) and re.fullmatch(r'[A-Za-z0-9_./-]+\.(json|toml)',x.value) and not SENSITIVE.search(x.value):config.add(x.value)
    config=sorted(config)
    line_map={motif:[] for motif in motifs}
    suffix_map={'.read_text':'lettura_file_locale','.read_bytes':'lettura_file_locale',
        '.write_text':'scrittura_file_locale','.write_bytes':'scrittura_file_locale',
        '.finditer':'segmentazione_testuale','.findall':'segmentazione_testuale',
        '.casefold':'normalizzazione_testuale','.lower':'normalizzazione_testuale',
        '.sha256':'impronta_crittografica','.get':'consultazione_struttura_dati'}
    for n in nodes:
        if isinstance(n,ast.Call):
            call=call_name(n.func)
            for suffix,motif in suffix_map.items():
                if call.endswith(suffix) and motif in line_map:line_map[motif].append(n.lineno)
            for call_expected,motif in [('json.dumps','serializzazione_json'),('json.dump','serializzazione_json'),('ast.parse','ispezione_sorgenti_python'),('sys.addaudithook','controllo_accessi_runtime')]:
                if call==call_expected and motif in line_map:line_map[motif].append(n.lineno)
        if 'ricerca_testuale_locale' in line_map and isinstance(n,ast.Compare) and any(isinstance(o,ast.In) for o in n.ops):line_map['ricerca_testuale_locale'].append(n.lineno)
        if 'aggiornamento_stato_locale' in line_map and isinstance(n,ast.Assign) and any(isinstance(t,(ast.Subscript,ast.Attribute)) for t in n.targets):line_map['aggiornamento_stato_locale'].append(n.lineno)
        if 'elaborazione_dati' in line_map and isinstance(n,ast.Return):line_map['elaborazione_dati'].append(n.lineno)
    line_map={k:sorted(set(v)) for k,v in line_map.items()}
    secret_refs = any(SENSITIVE.search(s) for s in strings) or any(isinstance(x, ast.Name) and SENSITIVE.search(x.id) for x in nodes)
    return {'motivi': sorted(set(motifs)), 'chiamate': [label(c) for c in calls], 'config_refs': config,
            'campi_sensibili_rilevati': bool(secret_refs), 'stub': not bool(meaningful),'linee_motivi':line_map}


def scan(root: Path, allowed: list[Path], *, phase_rnd: bool = True, additional_identity_files=()) -> dict:
    root = authorized_root(root, allowed)
    sources, metadata, excluded, errors = {}, {}, [], []
    secret_presence = False
    for folder, dirs, names in os.walk(root, followlinks=False):
        kept = []
        for name in sorted(dirs):
            p = Path(folder)/name
            if p.is_symlink() or name in EXCLUDE_DIRS or name.startswith('.'):
                excluded.append({'tipo': 'directory', 'motivo': 'ESCLUSA_O_LINK'})
            else: kept.append(name)
        dirs[:] = kept
        for name in sorted(names):
            p = Path(folder)/name
            rel = p.relative_to(root).as_posix()
            if p.is_symlink():
                excluded.append({'tipo': 'file', 'motivo': 'LINK_NON_SEGUITO'}); continue
            if name.startswith('.env') or SENSITIVE.search(name) or name.endswith(('.pem','.key')):
                secret_presence = True
                excluded.append({'tipo': 'file_sensibile', 'motivo': 'CONTENUTO_NON_LETTO'}); continue
            if not name.endswith('.py') and name not in META_FILES: continue
            if p.stat().st_size > 1024*1024:
                errors.append({'path': label(rel), 'motivo': 'LIMITE_DIMENSIONE'}); continue
            raw = p.read_bytes()
            if name.endswith('.py'):
                sources[rel] = raw
            else: metadata[rel] = raw
            if len(sources) > 1000: raise ScopeError('LIMITE_FILE_SUPERATO')
    source_hashes = {k: digest(v) for k,v in sorted(sources.items())}
    components, evidences, file_imports, tests, constant_list = [], {}, {}, [], []
    def evidence(kind, rel, sha, start=1, end=1, **extra):
        obj = {'tipo': kind, 'fonte': label(rel), 'sha256': sha, 'linee': [start,end], **extra}
        key = 'EV-'+digest(obj)[:24]; evidences[key] = obj
        return key
    def add_component(rel, module, node, kind, qual):
        facts = structural_facts(node) if kind in {'FUNZIONE','METODO'} else {'motivi': [],'chiamate': [],'config_refs': [],'stub':False,'campi_sensibili_rilevati':False}
        ev = evidence('STRUTTURA_AST', rel, source_hashes[rel], node.lineno, node.end_lineno,
                      nodo=type(node).__name__, motivi=facts['motivi'], linee_motivi=facts.get('linee_motivi',{}), stub=facts['stub'])
        cid = rel+'::'+qual
        interfaces = [label(x.name) for x in node.body if isinstance(x, (ast.FunctionDef,ast.AsyncFunctionDef)) and not x.name.startswith('_')] if kind=='CLASSE' else ([label(node.name)] if not node.name.startswith('_') else [])
        row = {'COMPONENT_ID':cid, 'NOME':label(node.name),'TIPO':kind,'MODULO':module,
               'SOURCE_PATH':rel,'SOURCE_SHA256':source_hashes[rel],'PUBLIC_INTERFACES':interfaces,
               'DIPENDENZE':[],'CONFIG_DEPENDENCIES':facts['config_refs'],'ENTRYPOINTS':[],
               'TEST_REFERENCES':[], 'STATO':'RILEVATA','EVIDENCE_REFS':[ev], 'FIRMA':signature(node) if kind in {'FUNZIONE','METODO'} else None,
               'MOTIVI_STRUTTURALI':facts['motivi'],'LINEE_MOTIVI':facts.get('linee_motivi',{}),'CHIAMATE':facts['chiamate'], 'STUB':facts['stub'],
               'SPERIMENTALE':phase_rnd, 'LINEA':node.lineno,
               'HEALTH_READINESS_REFERENCES':[label(c) for c in facts['chiamate'] if any(w in c.lower() for w in ('health','ready','salute'))]}
        components.append(row)
        return row
    for rel, raw in sorted(sources.items()):
        try: tree=ast.parse(source_text(raw), filename=rel)
        except (SyntaxError, UnicodeError, ValueError):
            errors.append({'path':label(rel),'motivo':'AST_NON_ANALIZZABILE','sha256':source_hashes[rel]}); continue
        module=rel[:-3].replace('/','.').removesuffix('.__init__')
        file_imports[rel]=imports(tree,rel)
        module_experimental=phase_rnd or any(isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='__experimental__' for t in n.targets) and isinstance(n.value,ast.Constant) and n.value.value is True for n in tree.body)
        mev=evidence('MODULO_AST',rel,source_hashes[rel],1,max(1,len(source_text(raw).splitlines())))
        public=[label(n.name) for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and not n.name.startswith('_')]
        entry=any(isinstance(n,ast.If) and any(isinstance(x,ast.Constant) and x.value=='__main__' for x in ast.walk(n.test)) for n in tree.body)
        components.append({'COMPONENT_ID':rel+'::<modulo>','NOME':module,'TIPO':'MODULO','MODULO':module,
            'SOURCE_PATH':rel,'SOURCE_SHA256':source_hashes[rel],'PUBLIC_INTERFACES':public,'DIPENDENZE':[],
            'CONFIG_DEPENDENCIES':[],'ENTRYPOINTS':['__main__'] if entry else [],'TEST_REFERENCES':[],
            'STATO':'RILEVATA','EVIDENCE_REFS':[mev],'FIRMA':None,'MOTIVI_STRUTTURALI':[],'CHIAMATE':[],
            'STUB':False,'SPERIMENTALE':module_experimental,'LINEA':1,'HEALTH_READINESS_REFERENCES':[]})
        for n in tree.body:
            if isinstance(n,(ast.Assign,ast.AnnAssign)):
                targets=n.targets if isinstance(n,ast.Assign) else [n.target]
                for t in targets:
                    if isinstance(t,ast.Name):
                        secret=bool(SENSITIVE.search(t.id)); secret_presence |= secret
                        constant_list.append({'fonte':rel,'nome':'CAMPO_SENSIBILE' if secret else label(t.id),
                                              'tipo_ast':type(n.value).__name__,'valore_esposto':False,'SECRET_PRESENT':secret})
            if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                r=add_component(rel,module,n,'CLASSE' if isinstance(n,ast.ClassDef) else 'FUNZIONE',n.name)
                r['SPERIMENTALE']=module_experimental
                if isinstance(n,ast.ClassDef):
                    for m in n.body:
                        if isinstance(m,(ast.FunctionDef,ast.AsyncFunctionDef)):
                            x=add_component(rel,module,m,'METODO',n.name+'.'+m.name);x['SPERIMENTALE']=module_experimental
                elif n.name.startswith('test_') or ('test' in rel.lower() and any(isinstance(x,ast.Assert) for x in ast.walk(n))):
                    tests.append({'id':rel+'::'+n.name,'source_sha256':source_hashes[rel],
                                  'calls':structural_facts(n)['chiamate'],'assertions':sum(isinstance(x,ast.Assert) for x in ast.walk(n)),
                                  'stato':'NON_ESEGUITO','riferimenti':[]})
    # Import resolution: exact package paths, plus root/src for script-style R&D projects.
    def resolve_import(imp, source):
        name=imp['modulo']; parts=name.split('.') if name else []
        if imp['livello']:
            parent=Path(source).parent
            for _ in range(imp['livello']-1): parent=parent.parent
            path=parent.joinpath(*parts).as_posix()
            options=[path+'.py',path+'/__init__.py']
        else:
            path='/'.join(parts)
            options=[path+'.py',path+'/__init__.py','src/'+path+'.py','src/'+path+'/__init__.py']
        local=next((x for x in options if x in sources),None)
        if local: return {'nome':name,'tipo':'LOCALE','path':local,'stato':'RILEVATA'}
        top=name.split('.')[0]
        if top in sys.stdlib_module_names or top=='__future__':
            return {'nome':name,'tipo':'LIBRERIA_STANDARD','path':None,'stato':'DISPONIBILE_NELL_INTERPRETE'}
        # Only a top-level spec lookup: never imports the inspected dependency.
        try:
            present=bool(top and PathFinder.find_spec(top,sys.path))
        except (ImportError,AttributeError,ValueError):
            present=False
        return {'nome':name,'tipo':'ESTERNA_NON_VERIFICATA','path':None,
                'stato':'INSTALLAZIONE_RILEVATA_NON_ESEGUITA' if present else 'NON_DISPONIBILE'}
    dependencies={rel:[resolve_import(i,rel) for i in vals] for rel,vals in file_imports.items()}
    # Track transitive unresolved local dependency chains conservatively.
    def missing(rel,seen=None):
        seen=set() if seen is None else seen
        if rel in seen:return []
        seen.add(rel); out=[]
        for d in dependencies.get(rel,[]):
            if d['stato']=='NON_DISPONIBILE':out.append(d['nome'])
            elif d['tipo']=='LOCALE':out+=missing(d['path'],seen)
        return sorted(set(out))
    configs={}
    for comp in components:
        rel=comp['SOURCE_PATH'];comp['DIPENDENZE']=dependencies.get(rel,[]);comp['DIPENDENZE_MANCANTI']=missing(rel)
        for name in comp['CONFIG_DEPENDENCIES']:
            cp=root/name
            if not cp.is_file():
                cp=root/Path(rel).parent/name
            valid=cp.is_file() and not cp.is_symlink() and cp.resolve().is_relative_to(root) and not SENSITIVE.search(name)
            # Configuration content is never exported; binding is a byte digest only.
            if valid and cp.stat().st_size<=1024*1024:
                configs[name]={'presente':True,'sha256':digest(cp.read_bytes())}
            else:configs[name]={'presente':False,'sha256':None}
        for test in tests:
            # References require an actual imported symbol and a matching AST call.
            rel_test=test['id'].split('::')[0]
            imported=any(d['path']==rel for d in dependencies.get(rel_test,[]))
            qual=comp['COMPONENT_ID'].split('::')[1]
            if imported and any(c==qual or c.endswith('.'+qual) or c.endswith('.'+comp['NOME']) for c in test['calls']):
                comp['TEST_REFERENCES'].append(test['id']);test['riferimenti'].append(comp['COMPONENT_ID'])
    identity={'NOME':None,'VERSIONE':None,'STATO':'UNKNOWN','EVIDENCE_REFS':[],'ORIGINE':None}
    for rel,raw in sorted(metadata.items()):
        try:
            d=tomllib.loads(raw.decode('utf-8-sig')) if rel.endswith('.toml') else json.loads(raw.decode('utf-8-sig'))
            meta=d.get('project',{}) if rel.endswith('.toml') else d
            name=meta.get('name') if rel.endswith('.toml') else meta.get('candidate')
            version=meta.get('version')
            if isinstance(name,str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,100}',name):
                identity={'NOME':name,'VERSIONE':str(version) if isinstance(version,(int,float,str)) and re.fullmatch(r'[A-Za-z0-9_.+-]{1,60}',str(version)) else None,
                          'STATO':'RILEVATA_DA_METADATA','ORIGINE':rel,
                          'EVIDENCE_REFS':[evidence('IDENTITA_METADATA',rel,digest(raw))]}; break
        except (UnicodeError,ValueError,TypeError):
            errors.append({'path':label(rel),'motivo':'METADATA_NON_INTERPRETABILI'})
    # A version constant is evidence of a version, not proof of a package/product name.
    versions=[]
    for rel,raw in sorted(sources.items()):
        try:tree=ast.parse(source_text(raw))
        except (SyntaxError,UnicodeError,ValueError):continue
        for n in tree.body:
            if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='__version__' for t in n.targets) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str):
                v=n.value.value
                if re.fullmatch(r'[A-Za-z0-9_.+-]{1,60}',v): versions.append({'fonte':rel,'versione':v,'evidenza':evidence('VERSIONE_METADATA',rel,source_hashes[rel],n.lineno,n.end_lineno)})
    inputs={'sorgenti':source_hashes,'metadata':{k:digest(v) for k,v in sorted(metadata.items())},'configurazioni':configs}
    if additional_identity_files:
        extra = {}
        for name in sorted(set(additional_identity_files)):
            p = root/name
            if p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(root) or SENSITIVE.search(name) or p.stat().st_size > 1024*1024:
                raise ScopeError('UNSAFE_ADDITIONAL_IDENTITY_FILE')
            extra[name] = digest(p.read_bytes())
        inputs['product_dependencies'] = extra
    return {'schema':'ai22.self001.scan.v1','identity':identity,'versions':versions,'components':components,
            'imports':file_imports,'dependencies':dependencies,'tests':tests,'constants':constant_list,
            'evidence':evidences,'inputs':inputs,'tree_sha256':digest(inputs),'errors':errors,'excluded':excluded,
            'SECRET_PRESENT':secret_presence,'SECRET_CONTENTS_READ':0,
            'counts':{'FILES_SCANNED':len(sources),'MODULES_FOUND':sum(x['TIPO']=='MODULO' for x in components),
                      'CLASSES_FOUND':sum(x['TIPO']=='CLASSE' for x in components),
                      'FUNCTIONS_FOUND':sum(x['TIPO'] in {'FUNZIONE','METODO'} for x in components),
                      'COMPONENTS_FOUND':len(components),'TESTS_DISCOVERED':len(tests)}}
