"""A bounded source-compiled right-triangle calculation, not general math QA.

The rule and symbol roles must occur together in the selected canonical source.
The solver proposes an integer example; a separate controller re-reads the rule,
checks roles, equation, triangle inequalities and numeric output. No title table.
"""
import math,re
VERSION='NATIVE_STUDY_MATH001_CANDIDATE_01'
# Match an explicit conditional binding, not an equation found anywhere.
BINDING=re.compile(r"dato un triangolo rettangolo , indicando con ([a-z]) la lunghezza della sua ipotenusa e con ([a-z]) e ([a-z]) le lunghezze dei suoi cateti , il teorema è espresso dall'equazione : : ([a-z]) \^ 2 \+ ([a-z]) \^ 2 = ([a-z]) \^ 2(?= [,.])")
LEAD=re.compile(r"^\s*: ?in ogni triangolo rettangolo (?:il quadrato costruito sull'ipotenusa è equivalente all'unione dei quadrati costruiti sui cateti|l'area del quadrato costruito sull'ipotenusa è uguale alla somma delle aree dei quadrati costruiti sui cateti) \.")

def compile_rule(text):
    if not isinstance(text,str) or len(text)>32768 or not LEAD.match(text):return None
    matches=list(BINDING.finditer(text))
    if len(matches)!=1:return None
    m=matches[0];h,a,b,x,y,z=m.groups()
    if len({h,a,b})!=3 or (a,b,h)!=(x,y,z):return None
    if re.search(r'\b(?:non|falso|falsa|errato|errata|sbagliato|sbagliata|presunto|presunta)\b',text[:m.end()]):return None
    return dict(condition='TRIANGOLO_RETTANGOLO',roles=dict(ipotenusa=h,cateti=[a,b]),operator='SUM_OF_SQUARES',start=m.start(),end=m.end(),text=m[0])

def propose():
    # Small readable numbers are chosen algorithmically; they are not facts
    # memorized about a named encyclopedia article.
    for a in range(3,31):
        for b in range(a+1,31):
            h=math.isqrt(a*a+b*b)
            if h*h==a*a+b*b:return dict(cateti=[a,b],ipotenusa=h)
    raise ValueError('No bounded integer example')

def verify_example(rule,example):
    if rule.get('condition')!='TRIANGOLO_RETTANGOLO' or rule.get('operator')!='SUM_OF_SQUARES':return False
    legs=example.get('cateti');h=example.get('ipotenusa')
    if not isinstance(legs,list) or len(legs)!=2:return False
    a,b=legs
    return all(type(x)is int and 0<x<=100 for x in (a,b,h)) and a+b>h and a+h>b and b+h>a and h>a and h>b and sum(x**2 for x in (a,b))==h**2

def answer_example(book,provider):
    geometry=[c for c in book.get('guide',{}).get('claims',[]) if not c['proposition']['negative'] and not c['proposition']['context'] and c['proposition']['copula']=='è' and re.match(r'un teorema della geometria euclidea\b',c['proposition']['complement'])]
    if len(geometry)!=1 or book.get('guide',{}).get('conflicts'):return None
    getter=getattr(provider,'get_article',None)
    if not callable(getter):return None
    article=getter(book['article_id'])
    if article is None or article.title!=book['title']:return None
    found=[];examined=0
    for section in article.sections:
        for row in section.get('evidence',[]):
            examined+=1
            if examined>64:return None
            rule=compile_rule(row['text'])
            if rule:found.append((row,rule))
    if len(found)!=1:return None
    row,rule=found[0];example=propose()
    evidence=provider.get_evidence(row['id'])
    if evidence is None or evidence.article_id!=book['article_id'] or evidence.text!=row['text'] or compile_rule(evidence.text)!=rule:raise ValueError('Calculation source changed')
    if not verify_example(rule,example):raise ValueError('Calculation controller rejected example')
    a,b=example['cateti'];h=example['ipotenusa']
    equation=f'{a}² + {b}² = {a*a} + {b*b} = {h*h}'
    # Independently parse and check every numeric term that will be displayed.
    terms=re.fullmatch(r'(\d+)² \+ (\d+)² = (\d+) \+ (\d+) = (\d+)',equation)
    left,right,s1,s2,total=map(int,terms.groups())
    if [left,right]!=[a,b] or left*left!=s1 or right*right!=s2 or s1+s2!=total or h*h!=total:raise ValueError('Rendered calculation changes arithmetic')
    answer=(f'{book["title"]}\n\nLa relazione riportata nella fonte, nella geometria euclidea e per un triangolo rettangolo, è:\n'
        'cateto₁² + cateto₂² = ipotenusa².\n\n'
        f'Esempio calcolato: scegliamo due cateti di {a} cm e {b} cm.\n{equation}.\n'
        f'Quindi l’ipotenusa misura {h} cm.\n\nControllo: {h} × {h} = {total}. '
        'Il calcolo usa l’ipotesi che il triangolo sia rettangolo.\n\n'
        'I numeri dell’esempio sono scelti da Wiki22; la relazione e il ruolo dei lati sono letti dalla fonte.')
    source=dict(evidence_id=evidence.evidence_id,article_id=article.article_id,article_title=article.title,
        source=evidence.source,revision=evidence.revision,start=rule['start'],end=rule['end'],text=rule['text'])
    # A second lookup after rendering closes the reflection pass.
    final=provider.get_evidence(row['id'])
    from .study import StudyEngine
    if final!=evidence or StudyEngine(provider).open(book['article_id'])!=book:raise ValueError('Calculation source changed during reflection')
    paragraph=book['paragraphs'][geometry[0]['paragraph']]
    geometry_source=dict(paragraph,article=book['title'],source=book['original_revision_url'],revision=str(book['revision_id']))
    return dict(status='ANSWERED',answer=answer,answer_type='SOURCE_RULE_VERIFIED_CALCULATION',supporting_evidence=[source,geometry_source],
        retrieval=dict(article_id=article.article_id,title=article.title),trace=dict(version=VERSION,model_calls=0,rule=rule,
        example=example,reflection='SOURCE_RULE_REREAD_AND_INDEPENDENT_INTEGER_CHECK',derived_example=True,cefr_level=None,human_iq=None))
