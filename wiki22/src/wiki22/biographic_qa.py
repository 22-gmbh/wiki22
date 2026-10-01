"""Bounded Italian questions over independently reflected BIO001 source roles."""
from dataclasses import asdict
import re

# These productions ask for source fields; they do not establish facts.
PATTERNS = (
    (r'quanti anni aveva (.+) quando (?:è mort[oa]|morì)', 'età_morte', ('Nascita','Morte'), None),
    (r'a (?:che|quale) età (?:è mort[oa]|morì) (.+)', 'età_morte', ('Nascita','Morte'), None),
    (r'in (?:che|quale) anno nacque (.+)', 'nascita_anno', ('Nascita',), ('anno',)),
    (r'quando nacque (.+)', 'nascita_tempo', ('Nascita',), ('anno','giorno e mese')),
    (r'dove nacque (.+)', 'nascita_luogo', ('Nascita',), ('luogo',)),
    (r'qual(?:e| è|e è)? (?:la )?data di nascita di (.+)', 'nascita_tempo', ('Nascita',), ('anno','giorno e mese')),
    (r'in (?:che|quale) anno morì (.+)', 'morte_anno', ('Morte',), ('anno',)),
    (r'quando morì (.+)', 'morte_tempo', ('Morte',), ('anno','giorno e mese')),
    (r'dove morì (.+)', 'morte_luogo', ('Morte',), ('luogo',)),
    (r'chi (?:è|era|fu) (.+)', 'profilo', ('Attività', 'Nazionalità', 'Nascita', 'Morte'), None),
    (r'in quale anno (?:è|era) nat[oa] (.+)', 'nascita_anno', ('Nascita',), ('anno',)),
    (r'quando (?:è|era) nat[oa] (.+)', 'nascita_tempo', ('Nascita',), ('anno','giorno e mese')),
    (r'dove (?:è|era) nat[oa] (.+)', 'nascita_luogo', ('Nascita',), ('luogo',)),
    (r'in quale anno (?:è|era) mort[oa] (.+)', 'morte_anno', ('Morte',), ('anno',)),
    (r'quando (?:è|era) mort[oa] (.+)', 'morte_tempo', ('Morte',), ('anno','giorno e mese')),
    (r'dove (?:è|era) mort[oa] (.+)', 'morte_luogo', ('Morte',), ('luogo',)),
    (r'qual[ei] (?:attività|professione) (?:svolge|svolgeva) (.+)', 'attività', ('Attività',), ('attività',)),
    (r'di quale nazionalità (?:è|era) (.+)', 'nazionalità', ('Nazionalità',), ('nazionalità',)),
)

def question_plan(query):
    if not isinstance(query,str) or len(query)>240 or '\n' in query:return None
    text=' '.join(query.strip().removesuffix('?').split())
    if '?' in text or any(c in text for c in '<>{}=;'):return None
    for pattern,intent,groups,fields in PATTERNS:
        match=re.fullmatch(pattern,text,re.IGNORECASE)
        if match:
            topic=match[1].strip()
            if len(topic)>160 or not any(c.isalpha() for c in topic):return None
            return dict(topic=topic,intent=intent,groups=groups,fields=fields)
    return None

def answer_biographic(query,provider,adapter):
    plan=question_plan(query)
    if plan is None or not hasattr(provider,'biographic_record'):return None
    from wiki22.articles import ArticleComposer
    composer=ArticleComposer(provider,adapter)
    try:
        draft=composer.prepare(plan['topic'],biographic_only=True)
        if not draft['biographic_candidates']:
            draft=composer.prepare(plan['topic'])
        if not draft['biographic_candidates']:return None
        result=composer.reflect(draft)
    finally:composer.close()
    claims=[c for c in result['claims'] if c['proposition'].get('predicate')=='source_biographic_fields'
            and c['proposition']['group'] in plan['groups']]
    if plan['fields']:
        claims=[c for c in claims if any(k in plan['fields'] for k,_ in c['proposition']['fields'])]
    if plan['intent']=='profilo' and not any(c['proposition']['group']=='Attività' for c in claims):claims=[]
    trace=dict(query=query,biographic_question=plan,reflection='SOURCE_ROLES_AND_GENERATED_MEANING_CHECKED',
               conflicting_propositions=result['conflicting_propositions'],exhaustive_corpus_semantic_scan=False,
               model_calls=0)
    if not claims:
        return dict(status='NO_EVIDENCE',query=query,answer=None,supporting_evidence=[],
                    ai22_processing='BIOGRAPHIC_REFLECTION_REJECTED',trace=trace)
    from .biography_answers import realize
    natural=realize(plan,claims)
    if plan['intent']=='età_morte' and natural is None:
        return dict(status='NO_EVIDENCE',query=query,answer=None,supporting_evidence=[],
                    ai22_processing='EXACT_SOURCE_DATES_REQUIRED',trace=trace)
    if natural:trace['answer_realization']=natural[1]
    sources=[]
    for claim in claims:
        source=claim['source'];evidence=provider.get_evidence(source['evidence_id'])
        if evidence is None or evidence.text[source['start']:source['end']]!=source['excerpt']:
            raise ValueError('Source changed after biographic reflection')
        article=getattr(provider, "get_article_summary", provider.get_article)(evidence.article_id)
        sources.append(dict(asdict(evidence),library_name=article.metadata.get('library_name','') if article else '',**{k:v for k,v in source.items() if k not in {'text'}},text=source['excerpt']))
    trace['native_propositions']=[c['proposition'] for c in claims]
    trace['frozen_documentary_checks']=[c['documentary'] for c in claims]
    return dict(status='ANSWERED',query=query,answer=natural[0] if natural else '\n'.join(c['text'] for c in claims),
        answer_type='BIO001_LITERAL_SOURCE_ROLES_AFTER_REFLECTION',supporting_evidence=sources,
        ai22_processing='COMPLETE',ai22_decision='DOCUMENTED',native_decision='SOURCE_FIELDS_VERIFIED',
        retrieval=dict(article_id=sources[0]['article_id'],title=sources[0]['article_title']),
        knowledge_provider=provider.stats(),trace=trace)
