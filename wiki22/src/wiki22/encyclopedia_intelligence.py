"""Encyclopedia integration of existing MEMIDX/LOCO, native MEM and SELF/CAP.

No new general comprehension claim. Fresh selected evidence alone may answer.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
from .knowledge.atlas import Atlas
from .knowledge.memidx_candidate import KINDS
from .knowledge.multi import MultiLibraryProvider
from .native22_linguistic_guarded.session import NativeSession
from .self_inspection.service import SelfInspection


def selected_provider(service,mode,ids):
    selected=service.scope(mode,ids or [])
    providers={lid:service.provider(lid) for lid in selected}
    return (next(iter(providers.values())) if len(providers)==1 else MultiLibraryProvider(providers)),selected

def graph(service,topic,*,mode='UNIFIED',ids=None,kind='ENTITÀ',node=None):
    if not isinstance(topic,str) or not 1<=len(topic.strip())<=240:raise ValueError('Inserisci un argomento entro 240 caratteri')
    if kind not in KINDS or (node is not None and not isinstance(node,str)):raise ValueError('Vista del grafo non valida')
    with service.lock:
        provider,selected=selected_provider(service,mode,ids)
        atlas=Atlas(provider)
        try:
            stats=atlas.search(topic)
            nodes=atlas.nodes(kind)
            result=dict(topic=topic,scope=selected,stats=stats,kinds=list(KINDS),kind=kind,nodes=nodes[:120],total_nodes=len(nodes),model_calls=0)
            if node:
                evidence=atlas.resolve(node)
                for e in evidence:
                    alias=selected[0] if len(selected)==1 else e['library_id']
                    e['library_name']=service.registry.get(alias)['name']
                result.update(evidence=evidence,connections=atlas.connections(node)[:120],node=node)
            return result
        finally:atlas.close()

def journal(service):return service.state_dir/'encyclopedia-learning'/'observations.sqlite3'

def memory(service):
    with service.lock:
        session=NativeSession(journal(service))
        try:
            count,size=session.journal.execute('SELECT count(*),coalesce(sum(bytes),0) FROM observations').fetchone()
            recent=[]
            for body, in session.journal.execute('SELECT body FROM observations ORDER BY rowid DESC LIMIT 12'):
                d=json.loads(body);recent.append(dict(provenance=d['provenance'],excerpt=d['testo'][:240]))
            return dict(metrics=session.metrics(),observations=count,bytes=size,recent=recent,model_calls=0,
                note='Osservazioni locali e ipotesi lessicali persistenti. Lo scaffale conserva segnalibri. Nessun livello QCER o QI umano è misurato.')
        finally:session.close()

def observe(service,document,*,mode='UNIFIED',ids=None,budget=3):
    if type(budget) is not int or budget not in (1,3,8):raise ValueError('Budget di osservazione non valido')
    with service.lock:
        d=service.context_documents([document],mode,ids or [])[0]
        eids=list(dict.fromkeys(s['evidence_id'] for n in d['notes'] for s in n['spans']))[:budget]
        provider=service.provider(d['library_id']);session=NativeSession(journal(service))
        try:
            before=session.metrics();receipts=[session.observe(provider,e) for e in eids]
            # Revalidate the document as well as each canonical observation.
            service.context_documents([document],mode,ids or [])
            return dict(receipts=receipts,before=before,after=session.metrics(),title=d['title'],new_observations=sum(r['status']=='OBSERVED' for r in receipts),model_calls=0)
        finally:session.close()

def reason(service,document,question,*,mode='UNIFIED',ids=None):
    if not isinstance(question,str) or not 1<=len(question.strip())<=500:raise ValueError('Inserisci una domanda entro 500 caratteri')
    with service.lock:
        d=service.context_documents([document],mode,ids or [])[0]
        all_ids=list(dict.fromkeys(s['evidence_id'] for n in d['notes'] for s in n['spans']))
        # Source-wide truncation cannot authorize a possibly contradicted answer.
        if len(all_ids)>40:return dict(STATO='SCONOSCIUTA',MOTIVO='La voce supera 40 passaggi: il ragionamento verificabile non copre l’intero documento.',FONTI=[],MODEL_CALLS=0)
        session=NativeSession(journal(service))
        try:
            result=session.answer(question,service.provider(d['library_id']),all_ids)
            service.context_documents([document],mode,ids or [])
            return result
        finally:session.close()

def diagnose(service):
    root=Path(__file__).resolve().parents[2]
    result=SelfInspection(root).inspect(run_reviewed_probes=True)
    result.update(at=datetime.now(timezone.utc).isoformat(),model_calls=0,
        note='SELF001/CAP001: prove tecniche delimitate sul codice. Non misurano intelligenza umana o padronanza generale dell’italiano.')
    target=service.state_dir/'diagnosis-latest.json';temp=target.with_suffix('.tmp')
    temp.write_text(json.dumps(result,ensure_ascii=False,indent=2));temp.replace(target)
    return result
