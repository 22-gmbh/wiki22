"""Repeatable measured capabilities, never a fabricated human IQ/CEFR score."""
import copy
import hashlib
import json
from pathlib import Path
from datetime import datetime,timezone
from .native22_linguistic_guarded.session import make_engine
from .native22_linguistic_guarded.identity import verify_implementation
from .maturity_profile import evaluate_profile,describe_profile

RESOURCE=Path(__file__).with_name('resources')/'maturity_reference001.json'

def software_identity():
    root=Path(__file__).parent
    return hashlib.sha256(b''.join(str(p.relative_to(root)).encode()+hashlib.sha256(p.read_bytes()).digest()
        for p in sorted(root.rglob('*')) if p.is_file() and p.suffix in {'.py','.json'})).hexdigest()

def assess():
    identity=software_identity();native=verify_implementation();data=json.loads(RESOURCE.read_text());rows=[]
    for case in data['cases']:
        engine=make_engine()
        if case['kind']=='analysis':
            result=engine.analizza(case['text']);prop=result.get('PROPOSIZIONE');gold=case['expected']
            ok=prop is None if gold is None else bool(prop and all(prop.get(k)==v for k,v in gold.items()))
            rows.append(dict(id=case['id'],area=case['area'],passed=ok,task=case['text'],actual=prop or result.get('MOTIVO'),expected=gold,
                false_assertion=gold is None and prop is not None,kind='coverage' if gold else 'safety'))
        else:
            result=engine.rispondi(case['question'],[dict(SOURCE_REF='diagnostic://'+case['id'],testo=case['text'])],usa_memoria=False)
            ok=result['STATO']==case['status'] and (case['value'] is None or result.get('VALORE')==case['value'])
            rows.append(dict(id=case['id'],area='reasoning',passed=ok,task=case['question'],premises=case['text'],actual=result.get('VALORE'),status=result['STATO'],expected=case['value'],expected_status=case['status'],false_assertion=case['value'] is None and result['STATO']=='VERIFICATA',kind='coverage' if case['value'] else 'safety'))
            if case.get('expression'):
                rows.append(dict(id=case['id']+'-E',area='expression',passed=ok and result.get('RISPOSTA')==case['expression'],task=case['question'],actual=result.get('RISPOSTA'),expected=case['expression'],false_assertion=False,kind='coverage'))
    groups={}
    for area in ('language','reasoning','expression'):
        r=[x for x in rows if x['area']==area];coverage=[x for x in r if x['kind']=='coverage'];safety=[x for x in r if x['kind']=='safety']
        groups[area]=dict(passed=sum(x['passed'] for x in r),total=len(r),coverage_passed=sum(x['passed'] for x in coverage),coverage_total=len(coverage),safety_passed=sum(x['passed'] for x in safety),safety_total=len(safety),false_assertions=sum(x['false_assertion'] for x in r))
    profile=evaluate_profile()
    if software_identity()!=identity:raise ValueError('Software cambiato durante la valutazione.')
    return dict(schema='wiki22.maturity.receipt.v1',at=datetime.now(timezone.utc).isoformat(),software_sha256=identity,native_version=native['version'],suite=data['version'],suite_sha256=hashlib.sha256(RESOURCE.read_bytes()).hexdigest(),groups=groups,cases=rows,
        profile=profile,iq=None,language_level=None,reason_percentile=None,spoken_audio_level=None,calibrated=False,
        scope=data['scope'],speech='Audio non valutato; espressione misura soltanto tre risposte scritte controllate.',model_calls=0,personal_memory_used=False)

class Assessment:
    def __init__(self,root):self.root=Path(root);self.result=None;self.expected=None
    def run(self):
        result=assess();self.result=copy.deepcopy(result);self.expected=hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()
        directory=self.root/'.runtime/maturity';directory.mkdir(parents=True,exist_ok=True)
        filename=result['at'].replace(':','-')+'.json'
        (directory/filename).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        return copy.deepcopy(result)
    def current(self):
        if self.result is None:return None
        if hashlib.sha256(json.dumps(self.result,sort_keys=True).encode()).hexdigest()!=self.expected:raise ValueError('Risultato di autodiagnosi alterato.')
        if self.result['software_sha256']!=software_identity():raise ValueError('Ripeti la diagnosi: il software è cambiato.')
        return copy.deepcopy(self.result)

def describe_assessment(report):
    names={'language':'Grammatica e comprensione','reasoning':'Ragionamento e controllo','expression':'Espressione scritta'}
    lines=[describe_profile(report['profile']),'','DIAGNOSI GRAMMATICALE DI BASE','Prove interne sulla versione '+report['native_version'],'']
    for area,g in report['groups'].items():
        lines.append(f"{names[area]}: {g['passed']}/{g['total']} controlli riusciti.")
        lines.append(f"Compiti risolti: {g['coverage_passed']}/{g['coverage_total']}; controlli di prudenza: {g['safety_passed']}/{g['safety_total']}; affermazioni indebite: {g['false_assertions']}.")
    lines+=['','Da migliorare:']+[f"• {c['task']}" for c in report['cases'] if not c['passed']]
    lines+=['','Queste prove sono ripetibili e note al sistema: non certificano un livello A1–C2 o un QI.','QI / percentile umano: non calibrato. Livello linguistico A1–C2: non determinato.',report['speech'],'I casi di prova non vengono inseriti nella memoria personale.']
    return '\n'.join(lines)
