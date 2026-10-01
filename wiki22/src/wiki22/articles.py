"""Italian source-bound synthesis from a bounded local research graph.

The solver extracts explicit propositions; the controller re-reads canonical
spans, checks their semantic identity, detects contradictions and invokes the
frozen documentary primitive. Templates compose claims without world facts.
"""
from collections import defaultdict
from dataclasses import asdict, replace
import re

from .knowledge.atlas import Atlas, canonical_record, identity
from .knowledge.grounding import sentences
from .knowledge.propositions import parse_candidate, entity, compatible, normalize, _time
from .knowledge.memidx_candidate import digest
from . import biographic_articles as biography

MAX_CLAIMS = 12


def section_for(prop):
    if prop.years or prop.tense in {'past','future'}:
        return 'Cronologia'
    return {'definition_of':'Profilo', 'authored_by':'Opere',
            'located_in':'Luoghi e relazioni'}.get(prop.predicate, 'Relazioni documentate')


def display_name(value):
    particles={'di','del','della','delle','dello','dei','degli','e','da','in','a'}
    return ' '.join(w if w in particles else w[:1].upper()+w[1:] for w in value.split())


def render_claim(prop, excerpt=''):
    """Controlled realization retaining polarity, modifiers, location and time."""
    subject = display_name(prop.subject)
    obj = display_name(prop.object)
    direct = re.split(r'\s+(?:non\s+)?(?:è|era|fu|sarà)\s+',excerpt,maxsplit=1,flags=re.I)
    original_subject=re.sub(r"\s*'\s*","'",direct[0]) if direct else ''
    base=re.sub(r'\s*\([^()]*\)\s*$', '', original_subject)
    if entity(base)==prop.subject:
        subject=original_subject
    neg = 'non ' if prop.polarity == 'negative' else ''
    copula = {'current':'è','past':'era','future':'sarà'}.get(prop.tense,'è')
    for modifier in prop.modifiers:
        if modifier.startswith('ASPECT:'):
            copula=modifier.partition(':')[2]
    if prop.predicate == 'definition_of':
        text = f'{subject} {neg}{copula} {prop.object}'
    elif prop.predicate == 'located_in':
        verb = {'current':'si trova','past':'si trovava','future':'si troverà'}.get(prop.tense,'si trova')
        text = f'{subject} {neg}{verb} {prop.object}'
    elif prop.predicate == 'authored_by':
        text = f'L’autore di {display_name(prop.subject)} {neg}è {obj}'
    elif prop.predicate in {'capital_of','president_of'} or prop.predicate.startswith('property_of:'):
        head = {'capital_of':'capitale','president_of':'presidente'}.get(prop.predicate,
                prop.predicate.partition(':')[2])
        mods = [dict(political='politica',culture='culturale',economic='economica').get(m,m)
                for m in prop.modifiers]
        if prop.predicate == 'capital_of' and prop.modifiers == ('political',):
            mods = []
        if prop.predicate == 'capital_of' and prop.modifiers == ('political', 'de_facto'):
            mods = ['de facto']
        role = ' '.join([head,*mods])
        owner=display_name(prop.subject)
        prep="d'" if owner[:1].casefold() in 'aeiou' else 'di '
        if prop.predicate=='capital_of':
            text=f'La {role} {prep}{owner} {neg}{copula} {obj}'
        else:
            text=f'{obj} {neg}{copula} {role} {prep}{owner}'
    else:
        raise ValueError('Predicato non supportato dalla composizione')
    if prop.location:
        # Context may be a geographic qualifier or a literal connective.
        # Preserve its source preposition and wording; never turn 'in quanto'
        # into 'a quanto', or silently rewrite an unanalysed adjunct.
        context_text,_=_time(normalize(excerpt).rstrip(' .'))
        context=re.fullmatch(r'(.+),\s*(a|in)\s+(.+)',context_text,re.I)
        if context is None or entity(context[3])!=prop.location:
            raise ValueError('Qualificatore contestuale non riproducibile')
        text += ', '+context[2]+' '+context[3]
    if prop.years:
        text += (' nel ' + prop.years[0] if len(prop.years)==1
                 else ' dal ' + prop.years[0] + ' al ' + prop.years[1])
    text=re.sub(r'\s+([,;:.])',r'\1',text)
    return text[0].upper() + text[1:].rstrip(' .') + '.'


def read_proposition(sentence, title=''):
    # A controlled extension for biographies. Keep parenthetical identity
    # qualifiers and perfect-past aspect in the structured proposition.
    sentence=re.sub(r"\s*'\s*", "'", sentence)
    aspect = re.search(r'\s+(è\s+stat[oa])\s+(?=(?:un[ao]?|il|lo|la)\s)',sentence,re.I)
    converted = sentence
    annotations = []
    if aspect:
        converted=sentence[:aspect.start()]+' era '+sentence[aspect.end():]
        annotations.append('ASPECT:'+aspect[1].casefold())
    prop=parse_candidate(converted,title=title)
    if prop is None:
        return None
    if prop.predicate=='definition_of':
        subject=re.fullmatch(r'(.+?)\s*\(([^()]{1,160})\)',prop.subject)
        if subject:
            annotations.append('SUBJECT_NOTE:'+subject[2])
            prop=replace(prop,subject=entity(subject[1]))
    if annotations and prop.predicate!='definition_of':
        return None
    if annotations:
        prop=replace(prop,modifiers=prop.modifiers+tuple(annotations))
    return prop


def eligible(sentence, title):
    if not sentence.endswith('.') or not 8 <= len(sentence) <= 320:
        return None
    if re.search(r'[{}\[\]|<>/=&\\]|\b(?:secondo|se|qualora|afferma|sostiene|avrebbe|dovrebbe)\b', sentence, re.I):
        return None
    prop = read_proposition(sentence,title=title)
    if prop is None or not prop.certain or not prop.object:
        return None
    if prop.predicate not in {'definition_of','located_in','authored_by','capital_of','president_of'} and not prop.predicate.startswith('property_of:'):
        return None
    if prop.years:
        if len(prop.years)==1:
            if not re.search(r'\bnel\s+'+re.escape(prop.years[0])+r'\b',sentence,re.I):
                return None
        elif len(prop.years)==2:
            pattern=r'\bdal\s+'+re.escape(prop.years[0])+r'\s+(?:al|-)\s+'+re.escape(prop.years[1])+r'\b'
            if not re.search(pattern,sentence,re.I):
                return None
        else:
            return None
    if prop.polarity == 'negative' and not re.search(r'\bnon\s+(?:è|era|fu|sarà|si\s+trova|ha\s+scritto)\b', sentence, re.I):
        return None
    if prop.predicate.startswith('property_of:'):
        # Generic noun roles are accepted only in direct bearer -> role form,
        # with plain short arguments. Inverted descriptions and superlatives
        # require a richer grammar; never turn a verb phrase into a person.
        if prop.modifiers or len(prop.subject.split()) > 6 or len(prop.object.split()) > 5:
            return None
        direct = re.split(r'\s+(?:non\s+)?(?:è|era|fu|sarà)\s+', sentence, maxsplit=1, flags=re.I)
        if len(direct)!=2 or entity(direct[0]) != prop.object:
            return None
        if re.search(r'\b(?:e|o|considerat[oa]|stat[oa]|completat[oa])\b', prop.subject+' '+prop.object,re.I):
            return None
    unresolved = {'questo','questa','quello','quella','egli','ella','esso','essa','essi','esse','lui','lei','ciò','cio','qui','lì'}
    if set((prop.subject+' '+prop.object).casefold().split()) & unresolved:
        return None
    # Self-compatibility still checks argument structure and unresolved clauses.
    if not compatible(prop,prop).accepted:
        return None
    return prop


class ArticleComposer:
    def __init__(self, provider, adapter, *, native_session=None, cache_path=None):
        self.provider, self.adapter = provider, adapter
        self.native_session = native_session
        self.atlas = Atlas(provider,cache_path)

    def close(self):
        self.atlas.close()

    def prepare(self, topic, *, biographic_only=False):
        direct = getattr(self.provider, 'exact_topic_candidates', None)
        if biographic_only and direct is not None:
            rows = [canonical_record(self.provider, row['evidence_id']) for row in direct(topic, limit=8)]
            self.atlas.rows = {row['evidence_id']: row for row in rows}
            research = dict(mode='BOUNDED_EXACT_TITLE_BIOGRAPHIC_READING', evidence_examined=len(rows), model_calls=0)
        else:
            research = self.atlas.search(topic)
        target = entity(topic)
        candidates, seen = [], set()
        biographic_candidates = []
        for eid, row in self.atlas.rows.items():
            getter=getattr(self.provider,'biographic_record',None)
            if getter and entity(row['title'])==target:
                record=getter(eid)
                if record:
                    for proposition in biography.propositions(row['title'],record):
                        if (proposition['group']=='Nome e cognome'
                            and entity(' '.join(value for _,value in proposition['fields']))==target):
                            continue  # Do not repeat a name already given by the title.
                        biographic_candidates.append(dict(proposition=proposition,evidence_id=eid,
                            source_binding=identity(row),structure_binding=digest(record)))
            if self.native_session:
                self.native_session.observe(self.provider,eid)
            if biographic_only:
                continue
            for sentence,start,end in sentences(row['text']):
                prop = eligible(sentence,row['title'])
                if prop is None:
                    continue
                # Every statement must describe the topic, not a coincidental
                # mention somewhere else in a matching article.
                if target not in (prop.subject,entity(prop.object)):
                    continue
                key = digest(asdict(prop))
                if (key,eid) in seen:
                    continue
                seen.add((key,eid))
                candidates.append(dict(proposition=asdict(prop),evidence_id=eid,
                    start=start,end=end,excerpt=sentence,source_binding=identity(row)))
        draft = dict(topic=topic,research=research,candidates=candidates,biographic_candidates=biographic_candidates)
        self._prepared_identity = digest(draft)
        return draft

    def _reflect_biographic(self, draft, claims, sections):
        checked=[]
        for item in draft.get('biographic_candidates',[]):
            row=canonical_record(self.provider,item['evidence_id'])
            getter=getattr(self.provider,'biographic_record',None)
            record=getter(item['evidence_id']) if getter else None
            if (record is None or identity(row)!=item['source_binding']
                or digest(record)!=item['structure_binding'] or entity(row['title'])!=entity(draft['topic'])):
                raise ValueError('Fonte o struttura biografica cambiata')
            candidates=biography.propositions(row['title'],record)
            if not any(digest(prop)==digest(item['proposition']) for prop in candidates):
                raise ValueError('Ruoli biografici non riproducibili dalla fonte')
            checked.append((item['proposition'],item,row,record))
        conflicts=set()
        for index,(left,_,_,_) in enumerate(checked):
            if left['group']=='Attività':continue
            for right,_,_,_ in checked[index+1:]:
                if entity(left['subject'])!=entity(right['subject']) or left['group']!=right['group']:continue
                first=dict(left['fields']);second=dict(right['fields'])
                if any(first[key]!=second[key] for key in first.keys() & second.keys()):
                    conflicts.update((digest(left),digest(right)))
        seen=set();documentary={}
        for prop,item,row,record in checked:
            key=digest(prop)
            if key in conflicts or key in seen or len(claims)>=MAX_CLAIMS:continue
            text=biography.render(prop)
            if digest(biography.parse_generated(text))!=digest(prop):
                raise ValueError('La frase generata altera i ruoli della scheda')
            begin,end=record['start'],record['end'];excerpt=row['text'][begin:end]
            doc_key=(item['evidence_id'],begin,end)
            if doc_key not in documentary:
                documentary[doc_key]=self.adapter.verify_excerpt(question='Scheda biografica: '+draft['topic'],
                    claim=excerpt,evidence=dict(evidence_id=item['evidence_id'],document_text=row['text'],start=begin,end=end))
            verdict=documentary[doc_key]
            if verdict.get('decision')!='DOCUMENTED':continue
            number=len(claims)+1;seen.add(key)
            source=dict(number=number,library_id=row['library_id'],article_id=row['article_id'],
                article_title=row['title'],source=row['source_ref'],revision=row['revision'],
                original_revision_id=record['revision_id'],
                original_revision_url='https://it.wikipedia.org/w/index.php?oldid='+str(record['revision_id']),
                evidence_id=item['evidence_id'],start=begin,end=end,excerpt=excerpt,
                source_binding=item['source_binding'],structure_binding=item['structure_binding'],
                biographic_index_sha256=record['index_sha256'])
            claims.append(dict(number=number,text=text,proposition=prop,source=source,
                reflection='SOURCE_FIELD_ROLES_AND_GENERATED_PROPOSITION_REPARSED',documentary=verdict))
            section='Cronologia' if prop['group'] in {'Nascita','Morte'} else 'Profilo biografico'
            sections[section].append(text+f' [{number}]')
        return len(conflicts)

    def reflect(self, draft):
        if digest(draft) != getattr(self, '_prepared_identity', None):
            raise ValueError('Ricerca o inventario delle proposizioni alterato')
        topic = draft['topic']
        target = entity(topic)
        checked = []
        for item in draft['candidates']:
            row = canonical_record(self.provider,item['evidence_id'])
            start,end = item['start'],item['end']
            if identity(row)!=item['source_binding'] or not 0 <= start < end <= len(row['text']):
                raise ValueError('Fonte cambiata durante la composizione')
            sentence = row['text'][start:end]
            if sentence != item['excerpt']:
                raise ValueError('Passaggio non corrispondente alla fonte')
            # Validate sentence boundaries: a substring of a conditional must
            # not be promoted to an independent assertion.
            if (sentence,start,end) not in list(sentences(row['text'])):
                raise ValueError('Confini della proposizione alterati')
            prop = eligible(sentence,row['title'])
            if prop is None or digest(asdict(prop)) != digest(item['proposition']):
                raise ValueError('Proposizione non riproducibile dalla fonte')
            if target not in (prop.subject,entity(prop.object)):
                raise ValueError('Proposizione estranea all’argomento')
            checked.append((prop,item,row))
        conflicts = set()
        for i,(left,_,_) in enumerate(checked):
            for right,_,_ in checked[i+1:]:
                comparable = (left.predicate,left.subject,left.modifiers,left.category,left.years,left.tense,left.location) == (right.predicate,right.subject,right.modifiers,right.category,right.years,right.tense,right.location)
                functional = left.predicate in {'capital_of','president_of'} or left.predicate.startswith('property_of:')
                if comparable and ((left.object==right.object and left.polarity!=right.polarity) or
                    (functional and left.polarity==right.polarity=='positive' and left.object!=right.object)):
                    conflicts.update((digest(asdict(left)),digest(asdict(right))))
        sections = defaultdict(list)
        claims, seen = [], set()
        for prop,item,row in checked:
            key = digest(asdict(prop))
            if key in conflicts or key in seen or len(claims)>=MAX_CLAIMS:
                continue
            verdict = self.adapter.verify_excerpt(question='Articolo: '+topic,
                claim=item['excerpt'], evidence=dict(evidence_id=item['evidence_id'],
                document_text=row['text'],start=item['start'],end=item['end']))
            if verdict.get('decision') != 'DOCUMENTED':
                continue
            seen.add(key)
            text = render_claim(prop,item['excerpt'])
            emitted = eligible(text,row['title'])
            if emitted is None or digest(asdict(emitted)) != digest(asdict(prop)):
                # The independently parsed generated sentence must preserve
                # every argument, time qualifier and polarity of the source.
                continue
            number = len(claims)+1
            source = dict(number=number,library_id=row['library_id'],article_id=row['article_id'],
                article_title=row['title'],source=row['source_ref'],revision=row['revision'],
                evidence_id=row['evidence_id'],start=item['start'],end=item['end'],
                excerpt=item['excerpt'],source_binding=item['source_binding'])
            claim = dict(number=number,text=text,proposition=asdict(prop),source=source,
                         reflection='SOURCE_AND_GENERATED_PROPOSITIONS_REPARSED',documentary=verdict)
            claims.append(claim)
            sections[section_for(prop)].append(text+f' [{number}]')
        bio_conflicts=self._reflect_biographic(draft,claims,sections)
        status = 'READY' if claims else ('CONFLICT' if conflicts or bio_conflicts else 'INSUFFICIENT_EVIDENCE')
        return dict(status=status,title=topic,sections=[dict(title=name,paragraphs=rows)
                    for name,rows in sections.items()],claims=claims,conflicting_propositions=len(conflicts)+bio_conflicts,
                    research=draft['research'],model_calls=0,offline=True,
                    synthesis='CONTROLLED_ITALIAN_PROPOSITIONS',
                    scope_note='Sintesi delle evidenze locali esaminate; non è una rassegna esaustiva del tema.',
                    native_metrics=self.native_session.metrics() if self.native_session else None)

    def compose(self, topic):
        return self.reflect(self.prepare(topic))
