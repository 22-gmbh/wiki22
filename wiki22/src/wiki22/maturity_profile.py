"""Task-based maturity profile with no conversion to human IQ or CEFR."""
from pathlib import Path
from time import perf_counter
import hashlib
import json
from .native22_linguistic_guarded.session import make_engine

RESOURCE=Path(__file__).with_name('resources')/'maturity_bands001.json'
BANDS=('A1','A2','B1','B2','C1','C2')
DOMAINS={'relations':'Relazioni esplicite','deduction':'Deduzione dichiarata','contradiction':'Contraddizioni','analogy':'Analogie','classification':'Classificazione','patterns':'Schemi e regole','multi_step':'Catene di inferenza'}
DESCRIPTORS={'A1':'Informazioni e frasi semplici','A2':'Tempo e riferimenti locali','B1':'Testi con nessi e contesto','B2':'Confronti, condizioni e spiegazioni','C1':'Impliciti e limiti delle conclusioni','C2':'Valutazione critica e più fonti'}


def score_rows(rows):
    return dict(solved=sum(r['passed'] for r in rows),total=len(rows),
        abstentions=sum(r['abstained'] for r in rows),incorrect_assertions=sum(r['incorrect_assertion'] for r in rows),
        milliseconds=round(sum(r['milliseconds'] for r in rows),3))


def internal_band(bands,*,safety_errors,minimum=4,threshold=1.0):
    level=None
    if safety_errors:return None
    for band in BANDS:
        g=bands[band]
        if g['total']<minimum or g['solved']/g['total']<threshold or g['incorrect_assertions']:break
        level=band
    return level


def evaluate_profile():
    raw=RESOURCE.read_bytes();suite=json.loads(raw);rows=[]
    for case in suite['cases']:
        engine=make_engine();start=perf_counter()
        if case['operation']=='analysis':
            actual=engine.analizza(case['text'],antecedenti=case['antecedents']);prop=actual.get('PROPOSIZIONE')
            passed=prop is not None and all(prop.get(k)==v for k,v in case['expected'].items())
            asserted=prop is not None;value=prop;status=actual.get('STATO');sources=[]
        else:
            actual=engine.rispondi(case['question'],[dict(SOURCE_REF='assessment://'+case['id'],testo=case['text'])],usa_memoria=False)
            value=actual.get('VALORE');status=actual['STATO'];asserted=status=='VERIFICATA';sources=actual.get('FONTI',[])
            passed=status==case['expected_status'] and (case['expected'] is None or value==case['expected'])
        rows.append(dict(case,id=case['id'],passed=passed,actual=value,status=status,sources=sources,
            abstained=not passed and not asserted,incorrect_assertion=asserted and not passed,
            milliseconds=round((perf_counter()-start)*1000,3)))
    if RESOURCE.read_bytes()!=raw:raise ValueError('Batteria modificata durante la valutazione.')
    bands={b:score_rows([r for r in rows if r['area']=='language' and r['band']==b]) for b in BANDS}
    domains={d:score_rows([r for r in rows if r['area']=='reasoning' and r['domain']==d]) for d in DOMAINS}
    safety=score_rows([r for r in rows if r['kind']=='safety'])
    language=score_rows([r for r in rows if r['area']=='language']);reason=score_rows([r for r in rows if r['area']=='reasoning'])
    # Any incorrect assertion, including a higher band, prevents a blanket level.
    level=internal_band(bands,safety_errors=sum(r['incorrect_assertion'] for r in rows),minimum=suite['minimum_per_band'],threshold=suite['internal_threshold'])
    return dict(schema='wiki22.maturity.profile.v1',suite=suite['version'],suite_sha256=hashlib.sha256(raw).hexdigest(),
        qi22=dict(solved=reason['solved'],total=reason['total'],percent=round(100*reason['solved']/reason['total'],1),human_iq=False,scope='Copertura dei soli compiti interni di ragionamento'),scope=suite['scope'],bands=bands,domains=domains,safety=safety,language=language,reasoning=reason,cases=rows,
        internal_band=level,internal_band_label='Fascia interna su questa batteria; non livello CEFR',
        threshold=suite['internal_threshold'],minimum_per_band=suite['minimum_per_band'],
        iq=None,human_percentile=None,certified_cefr=None,audio_level=None,calibrated=False,independent=False,
        calibration_missing=['Campione umano di riferimento e norme','Validità per il confronto umano/macchina','Valutazione indipendente e affidabilità','Compiti di interazione, produzione libera e audio'],
        model_calls=0,personal_memory_used=False)


def describe_profile(p):
    lines=['VALUTAZIONE A1–C2 E RAGIONAMENTO',
        f"Indice di ragionamento 22: {p['reasoning']['solved']}/{p['reasoning']['total']} compiti interni risolti. Non è un QI umano.",
        'QI umano: non calibrato. Nessuna conversione dei test in QI o percentile.',
        'Fascia interna dimostrata: '+(p['internal_band'] or 'nessuna completa')+' · NON è un livello CEFR.',
        'Soglia: tutti i compiti della fascia e delle precedenti; nessuna affermazione errata.',
        'Batteria interna nota: 4 compiti per fascia, senza calibrazione indipendente.','']
    for band,g in p['bands'].items():
        lines.append(f"{band} · {DESCRIPTORS[band]}: {g['solved']}/{g['total']} · astensioni {g['abstentions']} · risposte errate {g['incorrect_assertions']}")
    lines+=['','RAGIONAMENTO — profilo per dominio']
    for d,g in p['domains'].items():lines.append(f"{DOMAINS[d]}: {g['solved']}/{g['total']}")
    s=p['safety'];lines+=['',f"Controlli di prudenza separati: {s['solved']}/{s['total']}; affermazioni indebite {s['incorrect_assertions']}.",
        'Parlato e ascolto: non valutati. Produzione libera e interazione: non calibrate.','',
        'Per un QI confrontabile servono: '+'; '.join(p['calibration_missing'])+'.',
        'Apri «Dettaglio dei compiti» per domanda, premesse, risposta attesa e risultato effettivo.']
    return '\n'.join(lines)
