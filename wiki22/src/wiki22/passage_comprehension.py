"""COMPREHENSION024: source-bound question frames and conversational reading.

Dependency parsing proposes structure; answers describe the supplied passage,
never certify world facts. No LLM, confidence threshold, or memorized answers.
"""
from dataclasses import dataclass, replace
from copy import deepcopy
import hashlib
import re
import threading
from wiki22.native22_study_interpreter.dependency_reader import solver, children, subtree

LOCK = threading.RLock()
WH = {'chi', 'cosa', 'dove', 'quando', 'perché', 'come', 'quanto', 'quale'}
NEG = {'non', 'mai', 'nessuno', 'niente', 'nulla', 'né', 'senza'}
MODAL = {'potere', 'dovere', 'volere', 'sembrare', 'parere', 'credere', 'ritenere', 'supporre', 'ipotizzare', 'immaginare', 'pensare'}
REPORT = {'dire', 'affermare', 'sostenere', 'raccontare', 'riferire', 'dichiarare', 'scrivere', 'annunciare'}
MONTHS = set('gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre'.split())
CLAUSE = {'acl', 'advcl', 'ccomp', 'xcomp', 'parataxis'}
# Discourse operators are attached to sentences they govern, never to every
# assertion merely because a trigger word occurs somewhere in the passage.
META = {'notizia','affermazione','dichiarazione','racconto','storia','versione','tesi','ipotesi','ricostruzione','data'}
EVALUATION = re.compile(r'(?:fals|errat|inesatt|inventat|smentit|rettificat|corrett)\w*', re.I)


def report_kind(ts, root):
    if root.lemma not in REPORT:
        return None
    cs=children(ts,root.id)
    if any(t.rel in {'ccomp','xcomp','parataxis'} for t in cs) or any(t.form in {'«','»','“','”','"'} for t in ts):
        return 'embedded'
    objects=[t for t in cs if t.rel=='obj' and t.lemma in META]
    if any(any(c.lemma in {'questo','seguente'} for c in children(ts,t.id)) for t in objects) or any(t.form==':' for t in ts):
        return 'introduction'
    return None


def discourse_contexts(sentences):
    spans=[(min(t.lo for t in ts),max(t.hi for t in ts)) for ts in sentences]
    flags=[set() for ts in sentences]
    contexts=[set() for ts in sentences]
    introduction=None
    for i,ts in enumerate(sentences):
        root=next(t for t in ts if t.head==0)
        lemmas={t.lemma for t in ts}
        meta=[t for t in ts if t.lemma in META]
        # Attributive 'corretto' on an unrelated noun is not a retraction.
        evaluated_meta=any(any(EVALUATION.fullmatch(c.form) for c in children(ts,t.id)) and
                           (any(c.lemma=='questo' for c in children(ts,t.id)) or
                            t.lemma=='data' and root.pos=='NUM' and not lemmas & NEG and any(c.rel=='cop' for c in children(ts,root.id)))
                           for t in meta)
        evaluative_predicate=(bool(EVALUATION.fullmatch(root.form)) and bool(meta) and
                               (not lemmas & NEG or root.lemma=='corretto'))
        implicit_retraction=(
            ('vero' in lemmas and bool(lemmas & NEG)) or
            (root.lemma in {'accadere','succedere','avvenire'} and bool(lemmas & NEG) and not any(t.rel.startswith('nsubj') for t in ts)) or
            (root.lemma in {'sbagliare','mentire'} and not any(t.rel.startswith('nsubj') for t in ts)) or
            (root.lemma=='trattare' and bool(lemmas & {'fantasia','finzione','menzogna'})) or
            (bool(lemmas & NEG) and bool(lemmas & {'così','ciò'}))
        )
        retraction=evaluated_meta or evaluative_predicate or implicit_retraction or root.lemma in {'smentire','rettificare','mentire','sbagliare'}
        if retraction:
            flags[i].add('retracted')
            # Restrictive complements identify a particular claim. Do not
            # pretend to resolve them to the preceding, unrelated assertion.
            specified=any(c.rel in {'acl','acl:relcl','nmod'} for t in meta for c in children(ts,t.id))
            if i and not specified and (implicit_retraction or meta):
                flags[i-1].add('retracted');contexts[i-1].add(spans[i])
            elif i:
                # Explicitly named targets are compared with earlier mentions.
                # This only narrows a conservative retraction guard; overlap
                # never authorizes a factual answer.
                targets={t.form.casefold() if t.pos=='PROPN' else t.lemma for t in ts
                         if t.pos in {'PROPN','NOUN','VERB'} and t.id!=root.id
                         and t.lemma not in META and not EVALUATION.fullmatch(t.form)}
                for j,earlier in enumerate(sentences[:i]):
                    mentions={t.form.casefold() if t.pos=='PROPN' else t.lemma for t in earlier}
                    if targets & mentions:
                        flags[j].add('retracted');contexts[j].add(spans[i])
        if introduction is not None:
            flags[i].add('reported_context');contexts[i].add(spans[introduction])
        kind=report_kind(ts,root)
        if kind:
            flags[i].add('reported')
            if kind=='introduction':introduction=i
    return flags,contexts


def explain_reading(previous):
    proofs=previous['proofs']
    if previous.get('reason')=='QUALIFIED_SOURCE':
        scopes=set(previous.get('qualification_reasons',[])) or {s for p in proofs for s in p['scope']}
        if 'contradictory_polarity' in scopes:
            return 'Il testo afferma e nega lo stesso evento. Le due versioni sono incompatibili: non ne scelgo una senza un chiarimento.'
        if 'negative_restriction' in scopes:
            return 'La negazione riguarda un caso delimitato, per esempio da una data o da un luogo. La domanda è più ampia: togliere quel limite cambierebbe il significato.'
        if 'retracted' in scopes:
            return 'Il testo contiene una smentita o una rettifica della risposta candidata. Per questo non la presento come confermata.'
        if 'negative' in scopes:
            return 'La domanda presuppone che l’evento sia avvenuto, ma il passaggio lo nega nel caso descritto. Quel passaggio non sostiene una risposta affermativa.'
        if scopes & {'reported','reported_context'}:
            return 'Il passaggio presenta un racconto o una dichiarazione attribuita a qualcuno. Questo documenta ciò che viene raccontato, senza confermare da solo che sia avvenuto.'
        return 'Il passaggio contiene una condizione, un’incertezza o una limitazione. La risposta deve conservarla; non posso trasformarla in una conferma senza condizioni.'
    p=proofs[0];kind=previous.get('question_kind');value=p['value']
    if kind=='perché':
        return 'Stai chiedendo il motivo. Il testo collega l’evento descritto a questa causa: «'+value.rstrip('. ')+'». La risposta deriva da quel collegamento esplicito, non dalla sola vicinanza delle due frasi.'
    labels={'chi':'quale persona','cosa':'quale oggetto','dove':'quale luogo','quando':'quale momento','anno':'quale anno','come':'in quale modo','quale':'quale elemento'}
    request=labels.get(kind,'quale elemento')
    subject=p.get('subject')
    context=(' Il passaggio parla di «'+subject+'».') if subject and kind!='chi' else ''
    if previous.get('question_polarity')=='negative':
        return 'Stai chiedendo '+request+' sia associato all’azione negata nel caso descritto.'+context+' Il testo indica «'+value+'»; la negazione resta parte della risposta.'
    action=p.get('action')
    context+=(' L’azione è espressa da «'+action+'».') if action else ''
    labels={'chi':('la persona coinvolta','La persona indicata'),'cosa':('l’oggetto coinvolto','L’oggetto indicato'),'dove':('il luogo','Il luogo indicato'),'quando':('il momento','Il momento indicato'),'anno':('l’anno','L’anno indicato'),'come':('il modo in cui avviene l’azione','Il modo descritto')}
    topic,conclusion=labels.get(kind,('l’elemento richiesto','L’elemento indicato'))
    return 'La domanda riguarda '+topic+'.'+context+' '+conclusion+' è «'+value+'».'



def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def feats(t):
    return dict(x.split('=', 1) for x in t.feats.split('|') if '=' in x)


def nodes(ts, t):
    """A nominal expression, without subordinate assertions attached to it."""
    result = [t]
    for c in children(ts, t.id):
        if c.rel.split(':')[0] not in CLAUSE and c.rel != 'punct':
            result.extend(nodes(ts, c))
    return sorted(result, key=lambda x: x.id)


def key(ts, t):
    # Proper names are surface identities: the parser can lemmatize Leonardo
    # as 'leonardare'. Ignore only articles and the OUTER case marker.
    return tuple((x.form.casefold() if x.pos == 'PROPN' or x.form[:1].isupper() and x.pos in {'NOUN','PRON'} else x.lemma)
                 for x in nodes(ts, t) if not (x.head == t.id and x.rel == 'case')
                 and not (x.rel == 'det' and 'PronType=Art' in x.feats))


def case(ts, t):
    return tuple(x.lemma for c in children(ts, t.id) if c.rel == 'case' for x in nodes(ts, c))


def span(text, ts, t, outer=False):
    ns = nodes(ts, t)
    if not outer:
        ns = [x for x in ns if not (x.head == t.id and x.rel in {'case','det'})]
    return (min(x.lo for x in ns), max(x.hi for x in ns))


def tense(ts, r):
    ns = [r] + [x for x in children(ts, r.id) if x.rel.startswith('aux') or x.rel == 'cop']
    fs = [feats(x) for x in ns]
    if any(f.get('Mood') in {'Cnd','Sub','Imp'} for f in fs):
        return 'nonasserted'
    if any(f.get('Tense') == 'Fut' for f in fs): return 'future'
    if any(f.get('Tense') == 'Imp' for f in fs): return 'imperfect'
    # Present passive is not a past event merely because its participle is past.
    if any(x.rel == 'aux:pass' for x in ns) and any(feats(x).get('Tense') == 'Pres' for x in ns if x.rel == 'aux:pass') and not any(x.rel == 'aux' for x in ns): return 'present'
    if any(f.get('Tense') == 'Past' for f in fs): return 'past'
    if any(f.get('Tense') == 'Pres' for f in fs): return 'present'
    return None


@dataclass(frozen=True)
class Argument:
    role: str
    prep: tuple
    key: tuple
    span: tuple
    features: tuple = ()
    references: tuple = ()
    kind: str = ''


@dataclass(frozen=True)
class Frame:
    predicate: str
    tense: str
    arguments: tuple
    span: tuple
    scope: tuple
    wh: str = ''
    target: tuple = ()
    contexts: tuple = ()
    action: str = ''
    derivations: tuple = ()


def argument(text, ts, t):
    role = {'nsubj:pass':'obj', 'obl:agent':'nsubj'}.get(t.rel,t.rel)
    if t.pos=='NUM' and role=='nummod' and case(ts,t) in {('in',),('di',),('a',)}:role='obl'
    return Argument(role, () if t.rel == 'obl:agent' else case(ts,t), key(ts,t), span(text,ts,t), tuple(feats(t).items()),kind=t.pos)


def compatible(a,b):
    return a.role == b.role and a.prep == b.prep and a.key == b.key and all(not dict(a.features).get(f) or not dict(b.features).get(f) or dict(a.features)[f]==dict(b.features)[f] for f in ('Gender','Number'))


def parse_question(text):
    if len(text) > 512: return None
    with LOCK: sentences = solver().parse(text)
    if len(sentences) != 1: return None
    ts = sentences[0]; root = next(t for t in ts if t.head == 0)
    copular=any(t.rel=='cop' for t in children(ts,root.id))
    if (root.pos != 'VERB' and not copular) or root.lemma in MODAL: return None
    ws = [t for t in ts if t.lemma in WH and (t.head == root.id or t.id == root.id)]
    # 'in quale anno', 'che cosa': interrogative determiner is inside the slot.
    ws += [t for t in children(ts, root.id) if t not in ws and any(x.lemma in {'quale','che','quanto'} and 'PronType=Int' in x.feats for x in children(ts,t.id))]
    if len(ws) != 1: return None
    w = ws[0]; args=[]
    if any(t.lemma in MODAL for t in ts): return None
    negatives=[t for t in ts if t.lemma in NEG]
    if any(t.lemma!='non' or t.head!=root.id or t.rel!='advmod' for t in negatives):return None
    if any(t.rel.split(':')[0] in CLAUSE for t in ts): return None
    for t in children(ts,root.id):
        if t.id == w.id or t.rel == 'punct' or t.rel.startswith('aux') or t.rel=='cop' or t in negatives:continue
        if t.rel in {'nsubj','nsubj:pass','obj','iobj','obl','obl:agent','nummod'}:
            args.append(argument(text,ts,t))
        elif t.rel in {'expl','expl:pv'} and t.lemma=='si':
            args.append(Argument('reflexive',(),('si',),(t.lo,t.hi)))
        elif t.rel not in {'cc'}:return None
    wh = 'anno' if w.lemma=='anno' else 'quando' if w.lemma in {'mese','giorno','data'} else 'come' if w.lemma=='modo' else w.lemma
    target = ({'nsubj:pass':'obj','obl:agent':'nsubj'}.get(w.rel,w.rel),case(ts,w))
    if copular and w.id==root.id:target=('predicate',())
    if w.rel=='obl' and case(ts,w)==('da',) and any(t.rel=='aux:pass' for t in ts):target=('nsubj',())
    return Frame('@copula' if copular or root.lemma=='essere' else root.lemma,tense(ts,root),tuple(args),(0,len(text)),('negative',) if negatives else (),wh,target)


def resolve_argument(arg, t, entities):
    candidates=[]
    f=feats(t)
    gender=f.get('Gender') or {'lei':'Fem','lui':'Masc','essa':'Fem','esso':'Masc','ella':'Fem','egli':'Masc'}.get(t.lemma)
    number=f.get('Number')
    for ent in entities:
        ef=dict(ent.features)
        # Unknown gender remains a possible competitor, never infer from names.
        if gender and ef.get('Gender') and ef['Gender'] != gender: continue
        if number and ef.get('Number') and ef['Number'] != number: continue
        if ent.key not in [c.key for c in candidates]: candidates.append(ent)
    if len(candidates) != 1:return None
    ent=candidates[0]
    return replace(arg,key=ent.key,span=ent.span,features=ent.features,references=(arg.span,ent.span))


def read_frames(text):
    if not text.strip() or len(text)>16384:return [],'TEXT_BUDGET'
    with LOCK: sentences=solver().parse(text)
    if len(sentences)>100:return [],'TEXT_BUDGET'
    sentence_scopes,sentence_contexts=discourse_contexts(sentences)

    frames=[]; entities=[]; previous_span=None;previous_asserted=False
    for sentence_index,ts in enumerate(sentences):
        root=next(t for t in ts if t.head == 0)
        sentence_span=(min(t.lo for t in ts),max(t.hi for t in ts))
        roots=[root]+[t for t in ts if t.pos=='VERB' and (t.rel=='acl:relcl' or t.rel=='conj' and t.head==root.id)]
        new_entities=[]
        sentence_frames=[]
        for r in roots:
            copular=any(t.rel=='cop' for t in children(ts,r.id))
            if r.pos!='VERB' and not copular:continue
            scope=list(sentence_scopes[sentence_index]); args=[]; cs=children(ts,r.id)
            if any(t.rel=='cc' and t.lemma in {'o','oppure','ovvero'} for t in ts):scope.append('alternatives')
            if any(x.lemma in NEG for x in cs):scope.append('negative')
            if tense(ts,r)=='nonasserted' or r.lemma in MODAL or any(x.lemma in MODAL or x.lemma in {'forse','probabilmente','presumibilmente'} for x in cs):scope.append('hypothetical')
            if any(t.lemma=='se' for t in ts):scope.append('conditional')
            if any(t.form in {'«','»','“','”','"','?'} for t in ts):scope.append('quoted_or_questioned')
            if report_kind(ts,r):scope.append('reported')
            if any(x.rel in {'ccomp','xcomp','parataxis'} for x in cs):scope.append('embedded_scope')
            if r.rel=='acl:relcl':
                # Restrictive relatives under a negation, modal or hypothetical
                # are not projected as independent assertions.
                if any(t.lemma in NEG | MODAL | REPORT or feats(t).get('Mood') in {'Cnd','Sub'} for t in ts):scope.append('embedded_scope')
            if r.rel=='conj' and not any(t.lemma in {'e','ma'} and t.rel=='cc' for t in cs):scope.append('coordination_unresolved')
            if any(x.rel=='advmod' and x.lemma not in NEG | {'perciò','pertanto','quindi'} for x in cs):scope.append('qualified')
            if any(x.lemma in {'perciò','pertanto','quindi'} for x in cs):
                if previous_span and previous_asserted:args.append(Argument('cause',(),(),previous_span,references=(previous_span,)))
                else:scope.append('subordinate_scope')
            if r.rel=='conj' and sentence_frames:
                scope.extend(sentence_frames[0].scope)
            if any(t.lemma in {'solo','soltanto','quasi','circa','tranne','eccetto','salvo','secondo'} for t in ts):scope.append('qualified')
            for t in cs:
                if t.rel in {'nsubj','nsubj:pass','obj','iobj','obl','obl:agent','nummod'}:
                    a=argument(text,ts,t)
                    if t.pos=='PRON' and 'PronType=Rel' in t.feats and r.rel=='acl:relcl':
                        parent=next(x for x in ts if x.id==r.head)
                        base=argument(text,ts,parent)
                        a=replace(a,key=base.key,span=base.span,features=base.features,references=(a.span,base.span))
                    elif t.pos=='PRON' and (not t.form[:1].isupper() or t.lemma in {'lui','lei','egli','ella','esso','essa','essi','esse'}):
                        a=resolve_argument(a,t,entities)
                        if a is None:scope.append('ambiguous_reference');continue
                    args.append(a)
                    if t.pos in {'NOUN','PROPN'}:new_entities.append(a)
                elif t.rel in {'expl','expl:pv'} and t.lemma=='si':
                    args.append(Argument('reflexive',(),('si',),(t.lo,t.hi)))
                elif t.rel=='advcl':
                    marks=[x.lemma for x in children(ts,t.id) if x.rel=='mark']
                    if marks==['perché']:
                        sub=subtree(ts,t.id)
                        args.append(Argument('cause',(),(),(min(x.lo for x in sub),max(x.hi for x in sub))))
                    else:scope.append('subordinate_scope')
            if not any(a.role=='nsubj' for a in args) and not any(t.rel=='aux:pass' for t in cs):
                if r.rel=='conj' and sentence_frames:
                    subs=[a for a in sentence_frames[0].arguments if a.role=='nsubj']
                else:
                    unique={a.key:a for a in entities}
                    subs=list(unique.values()) if len(unique)==1 else []
                if len(subs)==1 and feats(r).get('Person')=='3':
                    a=subs[0];args.append(replace(a,role='nsubj',prep=(),references=(a.span,)))
                else:scope.append('missing_subject')
            if copular:
                excluded={x.id for x in cs if x.rel not in {'amod','nmod','det','case','flat','flat:name','compound'}}
                nominal_ts=[t for t in ts if t.id not in excluded]
                a=argument(text,nominal_ts,r)
                args.append(replace(a,role='predicate'))
            action=' '.join(t.form for t in ts if t.id==r.id or t.head==r.id and (t.rel.startswith('aux') or t.rel=='cop'))
            fr=Frame('@copula' if copular else r.lemma,tense(ts,r),tuple(args),sentence_span,tuple(scope),contexts=tuple(sorted(sentence_contexts[sentence_index])),action=action)
            frames.append(fr);sentence_frames.append(fr)
        # Only previous sentence entities participate in pronoun resolution.
        entities=list({a.key:a for a in new_entities}.values())
        previous_span=sentence_span
        previous_asserted=len(sentence_frames)==1 and not sentence_frames[0].scope
    return frames,None


def target_arguments(question, frame, text):
    w=question.wh
    candidates=[]
    for a in frame.arguments:
        raw=text[a.span[0]:a.span[1]]
        if w in {'quando','anno'}:
            if a.role not in {'obl','nummod'} or a.prep not in {(),('in',),('a',),('di',)}:continue
            if not(re.search(r'\b\d{3,4}\b',raw) or MONTHS.intersection(a.key)):continue
            if w=='anno':
                years=list(re.finditer(r'\b\d{3,4}\b',raw))
                if len(years)!=1:continue
                a=replace(a,span=(a.span[0]+years[0].start(),a.span[0]+years[0].end()))
        elif w=='dove':
            if a.role not in {'obl','predicate'} or a.prep not in {('a',),('in',),('presso',),('per',)}:continue
            if a.kind!='PROPN' or re.search(r'\d',raw) or MONTHS.intersection(a.key):continue
        elif w=='perché':
            if a.role!='cause':continue
        elif w=='come':
            if a.role!='obl' or not set(a.prep)&{'con','mediante','attraverso','grazie'}:continue
        elif w in {'chi','cosa','quale'}:
            if (a.role,a.prep)!=question.target:continue
        else:
            if (a.role,a.prep)!=question.target or not a.key or a.key[0]!=w:continue
        candidates.append(a)
    return candidates


class PassageConversation:
    """Bounded, source-specific dialogue; ambiguous turns clear ellipsis context."""
    def __init__(self):
        self.source_hash=None;self.scope=None;self.last=None;self.frames=[];self.error=None
        self.last_result=None

    def _read_frames(self, text):
        return read_frames(text)

    def _parse_question(self, question):
        return parse_question(question)

    def _candidate_frames(self, question):
        return self.frames

    def _remember_question(self, question, matches):
        subjects=tuple(a for a in matches[0][0].arguments if a.role=='nsubj')
        return replace(question,arguments=tuple(a for a in question.arguments if a.role!='nsubj')+subjects)

    def answer(self,question,text,*,source='provided-passage',scope=None):
        if not isinstance(question,str) or not isinstance(text,str):raise ValueError('Domanda e testo devono essere stringhe.')
        if len(question)>512 or len(text)>16384:raise ValueError('Domanda o passaggio oltre il limite di lettura.')
        sha=digest(text)
        if (sha,source,scope)!=(self.source_hash,self.scope, getattr(self,'selection',None)):
            self.last=None;self.last_result=None;self.frames,self.error=self._read_frames(text)
            self.source_hash=sha;self.scope=source;self.selection=scope
        question=question.strip()
        feedback=' '.join(question.casefold().strip(' ?!.').split())
        if feedback in {'dove lo dice','come lo sai','qual è la fonte','mostrami la frase'} and self.last_result:
            previous=deepcopy(self.last_result)
            return dict(previous,question=question,reason='EXPLAIN_PREVIOUS_READING',value=None,
                        answer='Mi baso su queste frasi del testo:\n'+'\n'.join('«'+s+'»' for p in previous['proofs'] for s in p.get('context_sentences',[])+[p['sentence']]),context_used=True)
        if feedback in {'non ho capito','spiegati meglio','spiegamelo meglio','puoi spiegare meglio'} and self.last_result:
            previous=deepcopy(self.last_result)
            return dict(previous,question=question,reason='SIMPLIFIED_READING',value=None,answer=explain_reading(previous),context_used=True)
        q=self._parse_question(question)
        used_context=False
        short=re.fullmatch(r'(?:[Ee]\s+)?(dove|quando|perché|come|chi|che cosa)\s*[?!.]?',question,re.I)
        if short and self.last:
            w=short[1].casefold();w='cosa' if w=='che cosa' else w
            q=replace(self.last,arguments=tuple(a for a in self.last.arguments if not(w=='chi' and a.role=='nsubj' or w=='cosa' and a.role=='obj')),wh=w,target=('nsubj',()) if w=='chi' else ('obj',()) if w=='cosa' else ('advmod',()))
            used_context=True
        if q and self.last:
            subjects=[a for a in self.last.arguments if a.role=='nsubj']
            if len(subjects)==1:
                resolved=[]
                for a in q.arguments:
                    if a.role=='nsubj' and a.kind=='PRON' and a.key in {('lei',),('lui',),('egli',),('ella',),('esso',),('essa',)}:
                        gender={'lei':'Fem','lui':'Masc','ella':'Fem','egli':'Masc','essa':'Fem','esso':'Masc'}[a.key[0]]
                        if dict(subjects[0].features).get('Gender',gender)==gender:
                            a=subjects[0];used_context=True
                    resolved.append(a)
                q=replace(q,arguments=tuple(resolved))
        if q and self.last and not any(a.role=='nsubj' for a in q.arguments) and q.wh!='chi':
            subjects=[a for a in self.last.arguments if a.role=='nsubj']
            if len(subjects)==1:q=replace(q,arguments=q.arguments+tuple(subjects));used_context=True
        base=dict(source=source,source_sha256=sha,question=question,reader='COMPREHENSION024',llm_calls=0,statistical_grammar_required=True,factual_answer_authorized=False,context_used=used_context,question_kind=q.wh if q else None,question_polarity='negative' if q and 'negative' in q.scope else 'positive')
        def unknown(reason,answer='Non riesco a collegare con sufficiente precisione questa domanda al testo.'):
            self.last=None;self.last_result=None
            return dict(base,status='CLARIFY',reason=reason,answer=answer,proofs=[])
        if self.error:return unknown(self.error,'Il testo contiene una rettifica o una struttura che non riesco ancora a interpretare con sicurezza.')
        if q is None:return unknown('QUESTION_STRUCTURE')
        matches=[];blocked=[]
        candidate_frames=self._candidate_frames(q)
        for f in candidate_frames:
            if f.predicate!=q.predicate:continue
            if not all(any(compatible(a,b) for b in f.arguments) for a in q.arguments):
                # A copular nominal property can occupy either side of the
                # surface copula; match the complete property, never keywords.
                if f.predicate=='@copula' and q.target==('predicate',()) and len(q.arguments)==1:
                    swapped=tuple(replace(a,role='predicate' if a.role=='nsubj' else 'nsubj' if a.role=='predicate' else a.role) for a in f.arguments)
                    if all(any(compatible(a,b) for b in swapped) for a in q.arguments):f=replace(f,arguments=swapped)
                    else:continue
                else:continue
            if any(s in f.scope for s in {'ambiguous_reference','missing_subject','subordinate_scope','embedded_scope','coordination_unresolved'}):blocked.append(f);continue
            if f.tense!=q.tense and f.tense!='nonasserted':continue
            if 'negative' in q.scope and 'negative' not in f.scope:continue
            targets=target_arguments(q,f,text)
            if len(targets)!=1:continue
            if 'negative' in q.scope:
                # A negative statement cannot lose temporal/place restrictions.
                unbound=[a for a in f.arguments if a is not targets[0] and a.span!=targets[0].span and not any(compatible(w,a) for w in q.arguments)]
                if unbound:f=replace(f,scope=f.scope+('negative_restriction',))
            matches.append((f,targets[0]))
        if not matches:
            if blocked:return unknown('UNRESOLVED_SCOPE_OR_REFERENCE','Il passaggio pertinente contiene un riferimento o una relazione ambigua: non scelgo un soggetto al suo posto.')
            return unknown('NO_MATCHING_RELATION','Non trovo nel testo un passaggio che risponda a questa relazione. Puoi precisare il soggetto o indicarmi la frase?')
        scopes={s for f,a in matches for s in f.scope}
        if any({'negative' in f.scope for f,a in matches if tuple(sorted((b.role,b.prep,b.key) for b in f.arguments))==signature}=={True,False} for signature in {tuple(sorted((b.role,b.prep,b.key) for b in f.arguments)) for f,a in matches}):scopes.add('contradictory_polarity')
        if 'negative' in q.scope:
            scopes.discard('negative')
            for f,a in matches:
                if any(g.predicate==f.predicate and g.tense==f.tense and 'negative' not in g.scope and all(any(compatible(x,y) for y in g.arguments) for x in f.arguments) for g in candidate_frames):scopes.add('contradictory_polarity')
        proofs=[]
        for f,a in matches:
            lo,hi=f.span
            context_spans=sorted({other.span for b in f.arguments for x in b.references for other in self.frames if other.span!=f.span and other.span[0]<=x[0]<x[1]<=other.span[1]})
            context_spans=sorted(set(context_spans)|set(f.contexts))
            subjects=[b for b in f.arguments if b.role=='nsubj']
            proofs.append(dict(derivations=list(f.derivations),action=f.action,subject=text[subjects[0].span[0]:subjects[0].span[1]] if len(subjects)==1 else None,context_spans=[list(x) for x in context_spans],context_sentences=[text[a:b] for a,b in context_spans],sentence=text[lo:hi],sentence_span=[lo,hi],answer_span=list(a.span),value=text[a.span[0]:a.span[1]],predicate=f.predicate,tense=f.tense,scope=list(f.scope),references=[list(x) for b in f.arguments for x in b.references]))
        values={p['value'].casefold() for p in proofs}
        if len(values)!=1 or len({tuple((a.role,a.key) for a in f.arguments if a.role in {'nsubj','obj'}) for f,a in matches})>1 and not q.arguments:
            self.last=None;self.last_result=None
            return dict(base,status='CLARIFY',reason='MULTIPLE_ANSWERS',answer='Il testo contiene più risposte possibili. A quale episodio ti riferisci?\n'+'\n'.join('«'+p['sentence']+'»' for p in proofs),proofs=proofs)
        if scopes:
            self.last=None
            label='nega questa premessa' if scopes=={'negative'} else 'presenta qualificazioni o incertezze che vanno mantenute'
            result=dict(base,status='READING',reason='QUALIFIED_SOURCE',qualification_reasons=sorted(scopes),answer='Il testo '+label+':\n'+'\n'.join('«'+s+'»' for p in proofs for s in p['context_sentences']+[p['sentence']]),proofs=proofs,value=None)
            self.last_result=deepcopy(result)
            return result
        # Save the matched subject, rather than a guessed topic; preserve other
        # question anchors, but not the extracted slot, for elliptical followups.
        self.last=self._remember_question(q,matches)
        result=dict(base,status='READING',reason='MATCHED_SOURCE_RELATION',value=proofs[0]['value'],answer=('Per il caso negato nella domanda, il testo indica: ' if 'negative' in q.scope else 'Nel testo: ')+proofs[0]['value'].rstrip('. ') +'.\n'+'\n'.join('«'+s+'»' for s in proofs[0]['context_sentences']+[proofs[0]['sentence']]),proofs=proofs)
        self.last_result=deepcopy(result)
        return result


def comprehend(question,text):
    return PassageConversation().answer(question,text)
