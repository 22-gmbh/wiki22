"""Read the native journal and collect human clarifications without promoting facts."""
import hashlib
import json
from pathlib import Path
from .native22_linguistic_guarded.session import NativeSession, make_engine


def learned_counts(engine):
    meanings = {item['SIGNIFICATO_ID'] for word in engine.lessico.values()
                if word['ORIGINE'] != 'SEME' for item in word['SIGNIFICATI_CANDIDATI'].values()
                if item['STATO'] in {'APPRESA', 'CONFERMATA'}}
    state = engine.metriche_stato()
    return dict(words=state['PAROLE_APPRESE'], meanings=len(meanings), entities=state['ENTITA'],
                relations=state['RELAZIONI_APPRESE'], propositions=state['PROPOSIZIONI_SUPPORTATE'],
                ambiguities_resolved=state['AMBIGUITA_RISOLTE_AUTONOMAMENTE'],
                human_questions=state['DOMANDE_GENERATE'])


def questions(session):
    answered = {row[0] for row in session.journal.execute('SELECT question_ref FROM user_assertions')}
    result = {}
    for question in session.engine.domande_umane:
        source = question['SOURCE_REF']
        if not source.startswith('WIKI22:'):
            continue  # Built-in curriculum is not a user's historical reading.
        observation = session.journal.execute('SELECT body FROM observations WHERE source_id=?', (source,)).fetchone()
        if observation is None:
            continue
        body = json.loads(observation[0])
        ref = 'LEARNING:' + hashlib.sha256(json.dumps(question, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        evidence = session.engine.evidenze[question['EVIDENCE_REF']]
        result[ref] = dict(id=ref, question=question['DOMANDA'], excerpt=evidence['testo'],
                           provenance=body['provenance'], answered=ref in answered)
    return list(result.values())


def snapshot(product_root):
    session = NativeSession(Path(product_root)/'.runtime/native22/memory.sqlite3')
    try:
        from .learning_background import recent_learning
        current = learned_counts(session.engine); baseline = learned_counts(make_engine())
        count, size = session.journal.execute('SELECT count(*), coalesce(sum(bytes),0) FROM observations').fetchone()
        assertions = session.journal.execute('SELECT count(*) FROM user_assertions').fetchone()[0]
        return dict(schema='wiki22.learning_snapshot.v1', observations=count, observation_bytes=size,
                    native_metrics=session.metrics(), learned_totals=current, curriculum_baseline=baseline,
                    growth_since_curriculum={k:current[k]-baseline[k] for k in current},
                    questions=questions(session), user_assertions=assertions,
                    dashboard=dashboard_metrics(session.engine), vocabulary=vocabulary_rows(session.engine), learning_events=recent_learning(product_root),
                    assertions_are_verified_facts=False, AI22_AUTONOMY_SCORE=None,
                    score_status='Needs a labeled benchmark; counters alone do not measure correctness')
    finally:
        session.close()


def record_clarification(product_root, question_id, answer):
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError('Scrivi un chiarimento prima di salvarlo.')
    session = NativeSession(Path(product_root)/'.runtime/native22/memory.sqlite3')
    try:
        selected = next((q for q in questions(session) if q['id'] == question_id), None)
        if selected is None:
            raise ValueError('La domanda non appartiene alle letture registrate.')
        if selected['answered']:
            raise ValueError('Questa domanda ha già un chiarimento registrato.')
        before = session.engine.metriche_stato()
        receipt = session.user_assertion(question_id, answer.strip())
        if before != session.engine.metriche_stato():
            raise ValueError('Un chiarimento non deve modificare la conoscenza verificata.')
        return receipt
    finally:
        session.close()


def dashboard_metrics(engine):
    from .native22_linguistic_guarded.session import RESOURCES
    grammar=json.loads((RESOURCES/'grammatica.json').read_text())
    rules=json.loads((RESOURCES/'regole_ragionamento.json').read_text())
    seed=json.loads((RESOURCES/'lessico_seme.json').read_text())
    state=engine.metriche_stato()
    return dict(known_forms=sum(r['known'] for r in vocabulary_rows(engine)),vocabulary_forms=state['FORME_LESSICALI'],
                acquired_forms=state['PAROLE_APPRESE'],hypotheses=state['IPOTESI_LESSICALI'],
                seed_forms=len(seed['voci']),grammar_productions=len(grammar['produzioni']),
                morphology_patterns=len(grammar['morfologia']),reasoning_rules=len(rules['regole'])+len(rules.get('regole_operative',[])),
                grammar_details=grammar['produzioni'],limitations=grammar['limiti'],
                language_level=None,iq=None,calibrated=False,
                count_scope='Native language kernel; forms include hypotheses, not the Wikipedia index')


def vocabulary_rows(engine):
    rows=[]
    for form,word in sorted(engine.lessico.items()):
        status='INIZIALE' if word['ORIGINE']=='SEME' else word['STATO']
        meanings=[dict(v) for v in word['SIGNIFICATI_CANDIDATI'].values()]
        rows.append(dict(form=form,status=status,known=status in {'INIZIALE','APPRESA','CONFERMATA'},meanings=meanings))
    return rows
