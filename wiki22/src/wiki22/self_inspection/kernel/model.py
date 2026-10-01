from __future__ import annotations
import copy
import platform
import sys
from .common import digest
from .probes import ProbeLedger


def build_model(scan: dict, ledger: ProbeLedger, *, runtime_policy: dict) -> dict:
    caps=[]; components=copy.deepcopy(scan['components']); evidence=copy.deepcopy(scan['evidence'])
    # Current-session receipts only; stale source/config tree stamps are rejected.
    valid={k:v for k,v in ledger.all().items() if v['tree_sha256']==scan['tree_sha256']}
    stale=len(ledger.all())-len(valid)
    for key,rec in valid.items():evidence[key]={'tipo':'SONDA_RUNTIME','dati':rec}
    for comp in components:
        cid=comp['COMPONENT_ID']
        refs=[k for k,r in valid.items() if cid in r['targets']]
        executed=[k for k in refs if cid in valid[k]['executed']]
        verified=[k for k in executed if valid[k]['status']=='PASS']
        failed=[k for k in refs if valid[k]['status'] in {'FAIL','TIMEOUT'}]
        config_missing=[k for k in comp['CONFIG_DEPENDENCIES'] if not scan['inputs']['configurazioni'].get(k,{}).get('presente')]
        if comp['DIPENDENZE_MANCANTI'] or config_missing: state='NON_DISPONIBILE'
        elif failed:state='ERRORE'
        elif verified:state='VERIFICATA'
        elif comp['CONFIG_DEPENDENCIES']:state='CONFIGURATA'
        else:state='RILEVATA'
        comp['STATO_VERIFICA']=state
        comp['STATO']='SPERIMENTALE' if comp['SPERIMENTALE'] and state in {'RILEVATA','CONFIGURATA','VERIFICATA'} else state
        comp['EVIDENCE_REFS']=sorted(set(comp['EVIDENCE_REFS']+refs))
        comp['CONFIG_MANCANTI']=config_missing
        for motif in comp['MOTIVI_STRUTTURALI']:
            public=bool(comp['PUBLIC_INTERFACES'])
            if not public or comp['STUB']:continue
            motif_verified=[k for k in verified if set(comp.get('LINEE_MOTIVI',{}).get(motif,[])) & set(valid[k].get('executed_lines',{}).get(comp['SOURCE_PATH'],[]))]
            capability_state=state if state!='VERIFICATA' or motif_verified else 'RILEVATA'
            display_state='SPERIMENTALE' if comp['SPERIMENTALE'] and capability_state in {'RILEVATA','CONFIGURATA','VERIFICATA'} else capability_state
            cap={'CAPABILITY_ID':'CAP-'+digest([cid,motif])[:20],'NOME':motif,'COMPONENTE':cid,
                 'STATO':display_state,'STATO_VERIFICA':capability_state,'SPERIMENTALE':comp['SPERIMENTALE'],
                 'EVIDENCE_REFS':comp['EVIDENCE_REFS'],'SONDE_VERIFICATE':motif_verified,'LINEE_STRUTTURALI':comp.get('LINEE_MOTIVI',{}).get(motif,[]),'TEST_REFERENCES':comp['TEST_REFERENCES'],
                 'LIMITI':['Un motivo AST propone una capacità, non dimostra semantica generale.',
                           'La verifica copre solo le sonde indicate, non tutti gli input.'],
                 'AUTORIZZAZIONE_PRODOTTO':False}
            caps.append(cap)
    runtime={'interprete':sys.implementation.name,'python':platform.python_version(),'sistema':platform.system(),
             'policy':runtime_policy,'probe_count':len(valid),
             'network_calls_observed':sum(r.get('audit',{}).get('NETWORK_CALLS',0) for r in valid.values()),
             'model_calls_observed':sum(r.get('audit',{}).get('MODEL_CALLS',0) for r in valid.values()),
             'probe_pass':sum(r['status']=='PASS' for r in valid.values()),
             'probe_fail':sum(r['status']!='PASS' for r in valid.values())}
    rev='RT-'+digest(runtime)[:24];evidence[rev]={'tipo':'STATO_PROCESSO_E_POLICY','dati':runtime}
    model={'schema':'ai22.state001.self_model.v1','IDENTITA':scan['identity'],'VERSIONI_RILEVATE':scan['versions'],
           'COMPONENTI':components,'CAPACITA':sorted(caps,key=lambda c:c['CAPABILITY_ID']),
           'DIPENDENZE':scan['dependencies'],'TEST_RILEVATI':scan['tests'],
           'RUNTIME':runtime,'RUNTIME_EVIDENCE':rev,'EVIDENZE':evidence,'SOURCE_TREE_SHA256':scan['tree_sha256'],
           'INPUT_HASHES':scan['inputs'],'RICEVUTE_OBSOLETE_IGNORATE':stale,
           'LIMITI':{'nessuna_coscienza_dichiarata':True,'scan_statico_non_esegue_sorgenti':True,
                     'sonde_solo_con_allowlist_revisionata':True,'sicurezza_python_non_sandbox_os':True,
                     'RC01_INTEGRITY':'NOT_VERIFIED_NO_BASELINE_BYTES','produzione_autorizzata':False}}
    return model


def diff_models(a: dict,b: dict) -> dict:
    ac={c['COMPONENT_ID']:c for c in a['COMPONENTI']};bc={c['COMPONENT_ID']:c for c in b['COMPONENTI']}
    old={c['CAPABILITY_ID']:c for c in a['CAPACITA']};new={c['CAPABILITY_ID']:c for c in b['CAPACITA']}
    return {'nuovi_componenti':sorted(bc.keys()-ac.keys()),'componenti_rimossi':sorted(ac.keys()-bc.keys()),
            'sorgenti_cambiate':sorted(k for k in a['INPUT_HASHES']['sorgenti'].keys()&b['INPUT_HASHES']['sorgenti'].keys()
                                       if a['INPUT_HASHES']['sorgenti'][k]!=b['INPUT_HASHES']['sorgenti'][k]),
            'nuove_capacita':sorted(new.keys()-old.keys()),'capacita_rimosse':sorted(old.keys()-new.keys()),
            'stati_cambiati':[{'id':k,'prima':old[k]['STATO_VERIFICA'],'dopo':new[k]['STATO_VERIFICA']}
                              for k in sorted(old.keys()&new.keys()) if old[k]['STATO_VERIFICA']!=new[k]['STATO_VERIFICA']]}
