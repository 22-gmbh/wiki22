from __future__ import annotations
import copy
import re
from pathlib import Path
from .common import digest
from .scanner import scan


def normalize_question(text: str) -> str:
    return ' '.join(re.sub(r'[?!.]', '', text.casefold()).split())


class SelfQuery:
    """Solver -> typed claims -> separate evidence controller -> fixed realization.
    This is bounded self-query routing, not general Italian language understanding.
    """
    def __init__(self, model: dict, root: Path, *, phase_rnd: bool, additional_identity_files=()):
        self.additional_identity_files=tuple(additional_identity_files)
        self.model=copy.deepcopy(model)
        self.expected_model_hash=digest(model)
        self.root=root.resolve();self.phase_rnd=phase_rnd

    def verify(self, claims: list[dict]) -> tuple[bool,str]:
        if digest(self.model)!=self.expected_model_hash:return False,'MODELLO_ALTERATO'
        current=scan(self.root,[self.root],phase_rnd=self.phase_rnd,additional_identity_files=self.additional_identity_files)
        if current['tree_sha256']!=self.model['SOURCE_TREE_SHA256']:return False,'FONTI_CAMBIATE_RIGENERARE_MODELLO'
        caps={c['CAPABILITY_ID']:c for c in self.model['CAPACITA']}
        comps={c['COMPONENT_ID']:c for c in self.model['COMPONENTI']}
        for c in claims:
            kind=c.get('tipo')
            if kind=='capacita':
                actual=caps.get(c.get('id'))
                if actual is None or c.get('stato')!=actual['STATO_VERIFICA']:return False,'CAPACITA_NON_SUPPORTATA'
                if c.get('evidenze')!=actual['EVIDENCE_REFS']:return False,'EVIDENZE_NON_COINCIDENTI'
                if c['stato']=='VERIFICATA':
                    if not actual['SONDE_VERIFICATE']:return False,'NESSUNA_SONDA_RIUSCITA'
                    for ref in actual['SONDE_VERIFICATE']:
                        rec=self.model['EVIDENZE'].get(ref,{}).get('dati',{})
                        if (rec.get('status')!='PASS' or rec.get('tree_sha256')!=current['tree_sha256']
                            or actual['COMPONENTE'] not in rec.get('executed',[])
                            or not (set(actual['LINEE_STRUTTURALI']) & set(rec.get('executed_lines',{}).get(actual['COMPONENTE'].split('::')[0],[])))):return False,'SONDA_NON_LEGATA_AL_COMPONENTE'
            elif kind=='identita':
                if c.get('nome')!=self.model['IDENTITA']['NOME'] or not c.get('nome'):return False,'IDENTITA_UNKNOWN'
                if c.get('evidenze')!=self.model['IDENTITA']['EVIDENCE_REFS']:return False,'IDENTITA_SENZA_FONTE'
            elif kind=='componente':
                actual=comps.get(c.get('id'))
                if not actual or c.get('evidenze')!=actual['EVIDENCE_REFS']:return False,'COMPONENTE_NON_SUPPORTATO'
            elif kind=='runtime':
                if c.get('id')!=self.model['RUNTIME_EVIDENCE'] or c.get('valore')!=self.model['RUNTIME'].get(c.get('campo')):return False,'RUNTIME_NON_SUPPORTATO'
            else:return False,'TIPO_CLAIM_NON_AMMESSO'
            if not c.get('evidenze') or any(e not in self.model['EVIDENZE'] for e in c['evidenze']):return False,'RIFERIMENTO_EVIDENZA_MANCANTE'
        return True,'CLAIM_VERIFICATI_CONTRO_FONTI_E_STATO'

    def answer(self, question: str, capability_ref: str|None=None) -> dict:
        q=normalize_question(question);m=self.model;claims=[]
        cap_by_id={c['CAPABILITY_ID']:c for c in m['CAPACITA']}
        def cc(c):return {'tipo':'capacita','id':c['CAPABILITY_ID'],'stato':c['STATO_VERIFICA'],'evidenze':c['EVIDENCE_REFS']}
        def rt(field):return {'tipo':'runtime','id':m['RUNTIME_EVIDENCE'],'campo':field,'valore':m['RUNTIME'][field],'evidenze':[m['RUNTIME_EVIDENCE']]}
        route='SELF_MODEL';status='VERIFICATA';text=''
        if q in {'come ti chiami','chi sei'}:
            i=m['IDENTITA']
            if i['NOME']:
                claims=[{'tipo':'identita','nome':i['NOME'],'evidenze':i['EVIDENCE_REFS']}]
                text='L’identità di questo pacchetto, rilevata nei metadata, è '+i['NOME']+'.'
            else:status='NON_VERIFICATO';text='Non ho un nome di pacchetto supportato da metadata autorevoli disponibili. Identità: UNKNOWN.'
        elif q in {'che cosa sai fare','cosa sai fare'}:
            verified=[c for c in m['CAPACITA'] if c['STATO_VERIFICA']=='VERIFICATA']
            selected=sorted(verified,key=lambda c:(c['NOME'],c['COMPONENTE']))[:6]
            if selected:
                claims=[cc(c) for c in selected]
                text='Nelle sonde indicate ho verificato: '+', '.join(c['NOME'].replace('_',' ')+' ('+c['COMPONENTE']+')' for c in selected)+'.'
                if any(c['SPERIMENTALE'] for c in selected):text+=' Sono componenti R&D: verifica locale non significa promozione in prodotto.'
            else:status='NON_VERIFICATO';text='Rilevo strutture software candidate, ma non dispongo di sonde riuscite che ne verifichino le capacità.'
        elif q in {'puoi usare internet','puoi accedere a internet'}:
            claims=[rt('policy')]
            if m['RUNTIME']['policy'].get('network_allowed') is False:
                text='No: l’accesso alla rete non è autorizzato in questa esecuzione. Questo è un vincolo runtime, non una deduzione dal nome dei moduli.'
            else:status='NON_VERIFICATO';text='La policy non basta a dimostrare che un accesso Internet funzioni; non lo dichiaro verificato.'
        elif q=='puoi lavorare offline':
            claims=[rt('probe_pass'),rt('network_calls_observed'),rt('policy')]
            if m['RUNTIME']['probe_pass']>0 and m['RUNTIME']['network_calls_observed']==0:
                text='Le sonde locali riuscite sono state eseguite senza operazioni di rete osservate, con rete vietata. Questo dimostra il funzionamento offline dei percorsi testati, non di tutto il software.'
            else:status='NON_VERIFICATO';text='La rete è vietata, ma mancano sonde riuscite sufficienti per dichiarare un percorso operativo offline.'
        elif q in {'quali librerie puoi usare','puoi leggere una libreria'}:
            selected=[c for c in m['CAPACITA'] if c['NOME']=='lettura_file_locale' and c['STATO_VERIFICA']=='VERIFICATA'][:4]
            claims=[cc(c) for c in selected]
            text=('Ho verificato lettura di file locali nei componenti indicati. ' if selected else 'Non ho una lettura di libreria verificata. ')
            text+='La presenza di dipendenze software non prova la disponibilità di una libreria di conoscenza, di RE001 o di un lettore 22CK.'
            if not selected:status='NON_VERIFICATO'
        elif q in {'quali capacità non sono disponibili','quali capacita non sono disponibili','quali capacità sono sperimentali','quali capacita sono sperimentali'}:
            experimental='sperimentali' in q
            selected=[c for c in m['CAPACITA'] if c['SPERIMENTALE']] if experimental else [c for c in m['CAPACITA'] if c['STATO_VERIFICA'] in {'NON_DISPONIBILE','ERRORE'}]
            selected=sorted(selected,key=lambda c:(c['COMPONENTE'],c['NOME']))[:8];claims=[cc(c) for c in selected]
            text=('Capacità sperimentali: ' if experimental else 'Capacità non disponibili o in errore: ')+('; '.join(c['COMPONENTE']+' / '+c['NOME']+' — '+c['STATO_VERIFICA'] for c in selected) if selected else 'nessuna accertata nel perimetro ispezionato')+'.'
            if not selected:status='NON_VERIFICATO'
        elif q in {'quali componenti supportano la ricerca','quali componenti hai'}:
            if q.endswith('la ricerca'):
                selected=[c for c in m['CAPACITA'] if c['NOME']=='ricerca_testuale_locale'];claims=[cc(c) for c in selected]
                text='Componenti con evidenza strutturale di ricerca: '+('; '.join(c['COMPONENTE']+' — '+c['STATO_VERIFICA'] for c in selected) if selected else 'non rilevati')+'.'
            else:
                selected=[c for c in m['COMPONENTI'] if c['TIPO']=='MODULO'][:12]
                claims=[{'tipo':'componente','id':c['COMPONENT_ID'],'evidenze':c['EVIDENCE_REFS']} for c in selected]
                text='Moduli ispezionati: '+', '.join(c['MODULO'] for c in selected)+'.'
            if not selected:status='NON_VERIFICATO'
        elif q in {'come sai che puoi fare questa cosa','quale test dimostra questa capacità','quale test dimostra questa capacita'}:
            selected=cap_by_id.get(capability_ref)
            if not selected:status='NON_VERIFICATO';text='Indica la capacità: non attribuisco un test a un riferimento ambiguo.'
            else:
                claims=[cc(selected)]
                if selected['SONDE_VERIFICATE']:
                    proof=[m['EVIDENZE'][e]['dati'] for e in selected['SONDE_VERIFICATE']]
                    text='La capacità '+selected['NOME']+' è supportata dalla struttura di '+selected['COMPONENTE']+' e dalle sonde '+', '.join(p['probe_id'] for p in proof)+', legate agli hash dei sorgenti e della configurazione. La verifica vale per gli input di quelle sonde.'
                else:status='NON_VERIFICATO';text='Ho soltanto evidenza strutturale o verifiche non riuscite per questa capacità: nessun test PASS applicabile.'
        else:status='NON_VERIFICATO';text='Questa domanda non rientra nelle interrogazioni del modello di sé. Non consulto una libreria esterna per inventare una risposta.'
        ok,reason=self.verify(claims)
        if not ok:status='NON_VERIFICATO';text='Non posso confermare la descrizione: '+reason+'.'
        refs=sorted({e for c in claims for e in c.get('evidenze',[])}) if ok else []
        return {'DOMANDA':question,'ROUTE':route,'STATO':status,'RISPOSTA':text,'CLAIM':claims if ok else [],
                'EVIDENCE_REFS':refs,'RIFLESSIONE':{'CONTROLLATO':True,'ESITO':reason,'CLAIM_SUPPORTATI':len(claims) if ok else 0,
                                                'CLAIM_RIFIUTATI':0 if ok else len(claims)},
                'MODEL_CALLS':0,'NETWORK_CALLS':0}
