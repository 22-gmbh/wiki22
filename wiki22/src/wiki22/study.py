"""Source-first study and conversation planning without a language model."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import time
import unicodedata
from .knowledge.atlas import browse_titles

STOP=set('il lo la i gli le un uno una di del della dello dei delle degli a al alla allo ai alle da dal dalla in nel nella con per su e è sono era che cosa chi qual quale come perché mi puoi potresti spiegare spiegami funziona funzionano si'.split())

def normalized(text):return ' '.join(unicodedata.normalize('NFKC',text).casefold().replace('’',"'").split())
def topic_text(text):
    text=text.strip().rstrip('?.!').strip()
    return re.sub(r"^(?:(?:il|lo|la|i|gli|le|un|una)\s+|l['’])",'',text,flags=re.I).strip()

def study_plan(query):
    text=' '.join(query.strip().rstrip('?.!').split())
    text=re.sub(r'^per favore[, ]+','',text,flags=re.I)
    text=re.sub(r'^(?:mi puoi spiegare|puoi spiegarmi|potresti spiegarmi|aiutami a capire)\s+','spiegami ',text,flags=re.I)
    if not text or len(text)>240:return None
    cause=re.fullmatch(r"perch[eé] (.{1,100}?) (?:è|sono|appare|appaiono|diventa|diventano) (.{1,100})",text,re.I)
    if cause and not re.search(r'\b(?:non|se|forse|quando)\b|\d',cause[1],re.I):
        return dict(topic=topic_text(cause[1]),intent='cause',premise=text,attribute=cause[2])
    patterns=(
        (r"(?:fammi|mostrami|fai) un esempio (?:di|su)\s+(.+)",'example'),
        (r"(?:spiegami|spiega|illustrami|descrivi|descrivimi|riassumi|approfondisci)\s+(.+)",'explain'),
        (r"(?:che (?:cos['’]è|cosa (?:è|sono))|cos['’]è|cosa sono|(?:che )?cosa significa)\s+(.+)",'definition'),
        (r"parlami (?:dell['’]|(?:di|del|della|dello|dei|degli|delle)\s+)(.+)",'study'),
        (r"(?:vorrei (?:studiare|capire)|voglio (?:studiare|capire)|studiamo)\s+(.+)",'study'),
        (r"(?:come (?:funziona|funzionano|avviene|avvengono))\s+(.+)",'process'),
    )
    for pattern,intent in patterns:
        m=re.fullmatch(pattern,text,re.I)
        if m:
            topic=m[1];depth=None
            suffix=re.search(r'\s+(passo per passo|in dettaglio|in modo semplice|in parole semplici)$',topic,re.I)
            if suffix:
                depth='detail' if suffix[1].casefold()=='in dettaglio' else 'step';topic=topic[:suffix.start()]
            result=dict(topic=topic_text(topic),intent=intent)
            if depth:result['depth']=depth
            return result
    return None

class DialogueContext:
    """An entity hint only: every factual answer still rereads selected sources."""
    def __init__(self):self.topic=None;self.scope=None;self.intent=None;self.choices=[]
    def resolve(self,query,scope,provider=None):
        if scope!=self.scope:self.topic=None;self.intent=None;self.choices=[];self.scope=scope
        if self.choices:
            choice=re.sub(r'^(?:quell[oaie]|intendevo|intendo)\s+','',normalized(query).rstrip('?.!'))
            words=topic_text(choice).split()
            matches=[x for x in self.choices if choice==normalized(x) or (1<=len(words)<=3 and all(w in normalized(x).split() for w in words))]
            if len(matches)==1:return 'Spiegami '+matches[0],matches[0]
            # Resolve a requested class only from a literal, affirmative
            # description in the current source, never from domain labels.
            requested=normalized(topic_text(choice))
            if not matches and provider is not None and re.fullmatch(r"[^\W\d_]+(?: [^\W\d_]+){0,2}",requested):
                engine=StudyEngine(provider);typed=[]
                for title in self.choices:
                    rows=engine.find(title)
                    if len(rows)!=1:continue
                    book=engine.open(rows[0]['article_id'])
                    if book['status']!='READY' or book['guide']['conflicts']:continue
                    for claim in book['guide']['claims']:
                        p=claim['proposition'];kind=normalized(topic_text(p['complement']))
                        kind=re.sub(r'^(?:prim[oa]|second[oa]|terz[oa]|quart[oa]|quint[oa]|sest[oa]|settim[oa]|ottav[oa]|non[oa]|decim[oa])\s+','',kind)
                        if not p['negative'] and p['copula']=='è' and (kind==requested or kind.startswith(requested+' ')):
                            if engine.open(book['article_id'])!=book:raise ValueError('Clarification source changed')
                            typed.append(title);break
                if len(typed)==1:return 'Spiegami '+typed[0],typed[0]
        if not self.topic:return query,None
        q=normalized(query).rstrip('?.!')
        bare=re.sub(r'^e\s+','',q)
        followups={
            'quando è nato':f'Quando è nato {self.topic}?','quando è nata':f'Quando è nata {self.topic}?',
            'dove è nato':f'Dove è nato {self.topic}?','dove è nata':f'Dove è nata {self.topic}?',
            'a che età è morto':f'A che età è morto {self.topic}?','a che età è morta':f'A che età è morta {self.topic}?',
            'quanti anni aveva quando morì':f'A che età morì {self.topic}?',
            'quando morì':f'Quando morì {self.topic}?','dove morì':f'Dove morì {self.topic}?',
            'quando nacque':f'Quando nacque {self.topic}?','dove nacque':f'Dove nacque {self.topic}?',
            'quando è morto':f'Quando è morto {self.topic}?','quando è morta':f'Quando è morta {self.topic}?',
            'dove è morto':f'Dove è morto {self.topic}?','dove è morta':f'Dove è morta {self.topic}?',
            'approfondisci':f'Approfondisci {self.topic} in dettaglio', 'spiegami meglio':f'Spiegami {self.topic} passo per passo',
            'più semplice':f'Spiegami {self.topic} passo per passo', 'in parole semplici':f'Spiegami {self.topic} passo per passo',
            'fammi un esempio':f'Fammi un esempio di {self.topic}',
            'un esempio':f'Fammi un esempio di {self.topic}',
            'fammi un riassunto':f'Riassumi {self.topic}', 'vorrei studiarlo':f'Vorrei studiare {self.topic}',
        }
        from .request_meaning import contextual, TEMPLATES, entity
        context_request=contextual(query)
        if context_request:
            if context_request.relation=='capital_of':
                return TEMPLATES['capital_of'].format(topic=self.topic),self.topic
            # An explicit geographic relation cannot introduce a birth/death
            # event. A study topic can: the source reader still checks the person.
            if self.intent in {'capital_of','continente','valuta','lingua','confini','governo','nomecompleto'}:
                return query,None
            if bare in followups:return followups[bare],self.topic
            return TEMPLATES[context_request.relation].format(topic=self.topic),self.topic
        if self.intent=='capital_of' and re.match(r"^e (?:dell['’]|(?:di|del|della|dello|il|la|lo)\s+)",q):
            other=re.sub(r"^(?:dell['’]|(?:di|del|della|dello|il|la|lo)\s+)",'',bare).strip()
            if entity(other) and len(other)<100:
                return f'Qual è la capitale di {other}?',self.topic
        if bare=='quanti anni aveva' and self.intent and self.intent.startswith('morte_'):
            return f'A che età morì {self.topic}?',self.topic
        if bare in {'dove','quando'} and self.intent:
            if self.intent.startswith('nascita_'):return f'{bare} nacque {self.topic}?',self.topic
            if self.intent.startswith('morte_'):return f'{bare} morì {self.topic}?',self.topic
        expanded=followups.get(bare)
        return (expanded,self.topic) if expanded else (query,None)
    def remember(self,query,result,scope):
        self.scope=scope
        if result.get('status')=='CLARIFY':
            self.topic=None;self.intent=None
            self.choices=[r['title'] for r in result.get('related_articles',[]) if isinstance(r,dict) and isinstance(r.get('title'),str)][:8]
        if result.get('status') in {'ANSWERED','READING'}:
            self.choices=[]
            plan=study_plan(query)
            from .biographic_qa import question_plan
            bio=question_plan(query)
            from .geography import question_plan as geographic_plan
            geo=geographic_plan(query)
            if geo:geo=dict(geo,intent='capital_of' if geo['field']=='capitale' else geo['field'])
            topic=(plan or bio or geo or {}).get('topic')
            if topic:self.topic=topic;self.intent=(plan or bio or geo)["intent"]
            else:
                retrieval=result.get('retrieval') or {}
                from .knowledge.propositions import analyze_query
                required=analyze_query(query).required
                self.intent=required.predicate if required else None
                self.topic=required.subject if required else retrieval.get('title')
        elif result.get('status')!='CLARIFY':self.topic=None;self.intent=None;self.choices=[]

class StudyEngine:
    def __init__(self,provider):self.provider=provider

    def find(self,topic):
        from .knowledge.propositions import normalize
        topic=normalize(topic_text(topic))
        if not topic or len(topic)>180:raise ValueError('Scegli un argomento tra 1 e 180 caratteri')
        rows=browse_titles(self.provider,topic,limit=16)
        exact=[r for r in rows if normalized(r['title'])==normalized(topic)]
        if exact:return exact
        return rows

    def open(self,article_id):
        getter=getattr(self.provider,'reading_record',None)
        book=getter(article_id) if getter else None
        if book and book['paragraphs']:
            book=dict(book)
            book['sections']=list(dict.fromkeys(p['heading'] for p in book['paragraphs']))
            book['questions']=[dict(prompt=f'Come spiegheresti «{h}» a parole tue?',heading=h,
                paragraph=next(i for i,p in enumerate(book['paragraphs']) if p['heading']==h)) for h in book['sections']]
            from .study_guide import build_guide
            book['guide']=build_guide(book)
            book['status']='READY'
            from .source_profile import geographic_profile
            profile=geographic_profile(self.provider,article_id)
            if profile:book['profile']=profile
            return book
        return dict(status='NO_STRUCTURED_READING',article_id=article_id,paragraphs=[],sections=[],questions=[])

    def answer(self,query):
        plan=study_plan(query)
        if plan is None or not callable(getattr(self.provider,'reading_record',None)):return None
        choices=self.find(plan['topic'])
        if not choices:return None
        if len(choices)!=1:
            return dict(status='CLARIFY',answer='Quale argomento intendi?\n'+'\n'.join('• '+r['title'] for r in choices[:8]),
                supporting_evidence=[],related_articles=choices[:8],trace=dict(study_plan=plan,model_calls=0))
        book=self.open(choices[0]['article_id'])
        if book['status']!='READY':
            alternatives=browse_titles(self.provider,choices[0]['title']+' (',limit=8)
            if alternatives:
                return dict(status='CLARIFY',query=query,answer='Quale significato intendi?\n'+'\n'.join('• '+r['title'] for r in alternatives),supporting_evidence=[],related_articles=alternatives,trace=dict(reason='QUALIFIED_TITLES_FOR_UNREADABLE_ENTRY',study_plan=plan,model_calls=0))
            return dict(status='CLARIFY',query=query,answer=f"Ho trovato la voce «{choices[0]['title']}», ma non ho ancora passaggi leggibili verificati per questa voce. Puoi consultarla in Esplora.",supporting_evidence=[],related_articles=choices,trace=dict(reason='READING_UNAVAILABLE_FOR_KNOWN_TOPIC',study_plan=plan,model_calls=0))
        if plan['intent']=='example' or plan.get('depth')=='step':
            from .study_math import answer_example
            calculation=answer_example(book,self.provider)
            if calculation is not None:return dict(calculation,query=query)
        paragraphs=book['paragraphs']
        from .study_guide import choose_passages
        indices,guide=choose_passages(book,plan['intent'],plan.get('depth','detail' if query.casefold().startswith('approfondisci') else 'standard'))
        causal_slices={}
        if plan['intent']=='cause':
            indices=sorted(guide['passages']['cause'],key=lambda i:(not bool(re.search(r'\b(?:perché|poiché)\b',paragraphs[i]['text'],re.I)),i))
            keys=[word for word in re.findall(r"[^\W\d_]+",plan['attribute'].casefold()) if len(word)>2 and word not in {'una','uno','del','dei','che','per','con','della','delle','degli'}]
            from .knowledge.grounding import sentences
            # A named subject + explicit copula + because-clause can offer the
            # source's own causal description even when the user's adjective
            # differs. This does not validate or silently replace the premise.
            expression=re.compile(r'(?<!\w)'+re.escape(book['title'])+r'\s+(?:è|sono|appare|appaiono|diventa|diventano)\s+.{1,180}?\b(?:perché|poiché)\b',re.I)
            for i in indices:
                for sentence,start,end in sentences(paragraphs[i]['text']):
                    if expression.search(sentence):
                        causal_slices[i]=dict(text=sentence,start=start,end=end);break
            indices=[i for i in indices if i in causal_slices or any(re.search(r'(?<!\w)'+re.escape(word)+r'(?!\w)',paragraphs[i]['text'],re.I) for word in keys)][:2]
            if not indices:
                return dict(status='CLARIFY',query=query,answer='Non ho verificato la premessa della domanda e non ho un passaggio sulle cause collegato a ciò che chiedi. Possiamo partire dalla descrizione della voce «'+book['title']+'».',supporting_evidence=[],related_articles=choices,trace=dict(reason='CAUSE_PREMISE_NOT_VERIFIED',study_plan=plan,model_calls=0))
        lesson=None
        if plan.get('depth')=='step' or plan['intent']=='example':
            from .study_lesson import build_lesson
            lesson=build_lesson(book,self.provider,purpose='example' if plan['intent']=='example' else 'step')
            cards=[c for c in lesson['cards'] if c['kind']=='example'] if plan['intent']=='example' else lesson['cards'][:1]
            if not cards:
                return dict(status='CLARIFY',answer='Non ho trovato un esempio esplicito nei passaggi di questa voce. Puoi aprire Studio e scegliere un concetto collegato.',supporting_evidence=[],related_articles=choices,trace=dict(study_plan=plan,model_calls=0))
            indices=list(dict.fromkeys(c['paragraph'] for c in cards))
        chosen=[paragraphs[i] for i in indices]
        # Independent reread validates the whole plan and every source slice.
        checked=self.open(book['article_id'])
        if checked!=book:raise ValueError('La fonte è cambiata durante la lettura')
        claims=[c for c in guide['claims'] if c['paragraph'] in indices]
        lines=[book['title']]
        if plan['intent']=='cause':lines.append('Per esaminare la domanda, ecco i passaggi sulle cause presenti nella voce locale. Non ho verificato separatamente la premessa della domanda.')
        if guide['conflicts']:
            lines.append('Nei passaggi disponibili ci sono descrizioni in contrasto: confronta le fonti prima di trarre una conclusione.')
        if plan['intent']=='definition' and not claims:
            lines.append('Non ho una definizione verificata in questi passaggi. Ecco la lettura disponibile, da cui puoi proseguire in Studio.')
        for i,p in zip(indices,chosen):
            if i in causal_slices:
                lines.extend(['La descrizione spiegata dalla fonte',causal_slices[i]['text']]);continue
            if lesson:
                lines.extend(['Un passaggio per iniziare' if plan['intent']!='example' else 'Esempio nella fonte',next(c['text'] for c in cards if c['paragraph']==i)])
                continue
            local=[c for c in claims if c['paragraph']==i]
            if local and plan['intent']=='definition' and not guide['conflicts']:
                lines.extend(['Definizione dalla voce locale',local[0]['text']])
            else:
                label='Passaggio dalla fonte'
                if i in guide['passages']['distinction']:label='Distinzione descritta nella fonte'
                elif i in guide['passages']['process']:label='Come viene descritto nella fonte'
                lines.extend([label,p['text']])
        if lesson and lesson['glossary']:
            lines.append('Termini da capire')
            for term in lesson['glossary']:lines.extend([term['title'],term['text']])
        if plan.get('depth')=='step':
            lines.append('Partiamo da questo passaggio. In Studio puoi aprire i termini collegati e provare a spiegarlo con parole tue.')
        else:lines.append('Puoi chiedermi un chiarimento o aprire la pagina enciclopedica con il pulsante sopra la conversazione.')
        sources=[dict(p,library_name=getattr(self.provider,'library_name',''),article=book['title'],
            revision=str(book['revision_id']),source=book['original_revision_url']) for p in chosen]
        if lesson:
            for term in lesson['glossary']:
                sources.append(dict(term['source'],article=term['title'],revision=str(term['revision'])))
        if book.get('profile') and plan['intent'] in {'study','explain','definition'}:
            lines[1:1]=['Quadro iniziale · dati della scheda locale',book['profile']['text']]
            sources=book['profile']['sources']+sources
        return dict(status='READING',query=query,answer='\n\n'.join(lines),answer_type='SOURCE_BOUND_STUDY_GUIDE',
            supporting_evidence=sources,retrieval=dict(article_id=book['article_id'],title=book['title']),
            trace=dict(study_plan=plan,lesson=lesson,source_reread=True,source_index=book['index_sha256'],model_calls=0,
                       verified_descriptions=claims,causal_source_slices=causal_slices,conflicts=guide['conflicts'],selected_paragraphs=indices,
                       query_premise_independently_verified=False if plan['intent']=='cause' else None,
                       complete_article=False,interpretation='STRUCTURED_READING_WITH_BOUNDED_DESCRIPTION_GRAMMAR'))

class StudyNotebook:
    """Local learner notes, never promoted to encyclopedic evidence."""
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.path)
        self.db.execute('PRAGMA busy_timeout=3000')
        self.db.execute('CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY,created REAL NOT NULL,scope TEXT NOT NULL,article TEXT NOT NULL,title TEXT NOT NULL,revision TEXT NOT NULL,body TEXT NOT NULL)')
        self.db.commit()
    def save(self,scope,book,body):
        body=body.strip()
        if not body:raise ValueError('Scrivi un appunto prima di salvarlo')
        with self.db:
            cursor=self.db.execute('INSERT INTO notes(created,scope,article,title,revision,body) VALUES (?,?,?,?,?,?)',
                (time.time(),json.dumps(list(scope)),book['article_id'],book['title'],str(book.get('revision_id','')),body))
        return cursor.lastrowid
    def list(self,scope,article_id):
        return [dict(id=i,created=c,body=b,revision=r) for i,c,b,r in self.db.execute(
            'SELECT id,created,body,revision FROM notes WHERE scope=? AND article=? ORDER BY id DESC LIMIT 100',
            (json.dumps(list(scope)),article_id))]
    def close(self):self.db.close()
