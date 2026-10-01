"""Controlled Italian descriptions of explicit biographical source fields.

These are source-reported roles, not inferred current professions, expanded
nationality codes or exact dates obtained by discarding source qualifiers.
"""
import re

GROUPS=(('Nome e cognome',('Nome','Cognome')),
        ('Attività',('Attività','Attività2','Attività3')),
        ('Nazionalità',('Nazionalità',)),
        ('Nascita',('LuogoNascita','GiornoMeseNascita','AnnoNascita')),
        ('Morte',('LuogoMorte','GiornoMeseMorte','AnnoMorte')))
LABELS={'Nome':'nome','Cognome':'cognome','Nazionalità':'nazionalità',
        'LuogoNascita':'luogo','LuogoMorte':'luogo',
        'GiornoMeseNascita':'giorno e mese','GiornoMeseMorte':'giorno e mese',
        'AnnoNascita':'anno','AnnoMorte':'anno'}


def literal(value):
    if not isinstance(value,str) or not 1<=len(value)<=120:
        return False
    if value!=value.strip() or re.search(r'[{}\[\]|<>/=&\\«»"\n\r;!?]',value):
        return False
    if re.search(r'\b(?:forse|probabilmente|non|ignoto|sconosciuto|presunto|secondo)\b',value,re.I):
        return False
    return True


def propositions(title,record):
    if not title or len(title)>180 or any(c in title for c in '«»\n\r'):
        return []
    values={key:item['value'] for key,item in record['fields'].items() if literal(item['value'])}
    result=[]
    for group,names in GROUPS:
        fields=tuple((key,values[key]) for key in names if key in values)
        if not fields:continue
        if group=='Attività':
            # Numeric slots do not imply a ranking, dates or a current job.
            fields=tuple(('attività',value) for _,value in fields)
        else:fields=tuple((LABELS[key],value) for key,value in fields)
        result.append(dict(predicate='source_biographic_fields',subject=title,
            group=group,fields=fields,statute='EXPLICIT_SOURCE_RECORD',inferred=False))
    return result


def display_value(label,value):
    if label not in {'nome','cognome','luogo'}:return value
    particles={'di','de','del','della','da','van','von','der','e'}
    return ' '.join(word if i and word in particles else word.title() for i,word in enumerate(value.split()))


def render(prop):
    title=prop['subject'];group=prop['group'];fields=prop['fields']
    if group=='Attività':
        values=['«'+value+'»' for _,value in fields]
        listing=values[0] if len(values)==1 else ', '.join(values[:-1])+' e '+values[-1]
        return f'La fonte biografica di «{title}» indica le attività {listing}.'
    labels=[label+' «'+display_value(label,value)+'»' for label,value in fields]
    listing=labels[0] if len(labels)==1 else ', '.join(labels[:-1])+' e '+labels[-1]
    if group=='Nome e cognome':return f'La scheda biografica di «{title}» riporta {listing}.'
    if group=='Nazionalità':return f'La scheda biografica di «{title}» indica la nazionalità «{fields[0][1]}».'
    return f'Per «{title}», la fonte riporta {group.casefold()}: {listing}.'


def parse_generated(text):
    """Independent full-sentence recognition of the controlled realization."""
    match=re.fullmatch(r'La fonte biografica di «([^«»]+)» indica le attività (.+)\.',text)
    if match:
        items=re.fullmatch(r'«([^«»]+)»(?: e «([^«»]+)»|, «([^«»]+)» e «([^«»]+)»)?',match[2])
        if not items:return None
        values=tuple(value for value in items.groups() if value is not None)
        if not all(literal(v) for v in values):return None
        return dict(predicate='source_biographic_fields',subject=match[1],group='Attività',
            fields=tuple(('attività',v) for v in values),statute='EXPLICIT_SOURCE_RECORD',inferred=False)
    nationality=re.fullmatch(r'La scheda biografica di «([^«»]+)» indica la nazionalità «([^«»]+)»\.',text)
    if nationality:
        if not literal(nationality[2]):return None
        return dict(predicate='source_biographic_fields',subject=nationality[1],group='Nazionalità',
            fields=(('nazionalità',nationality[2].casefold()),),statute='EXPLICIT_SOURCE_RECORD',inferred=False)
    name=re.fullmatch(r'La scheda biografica di «([^«»]+)» riporta (.+)\.',text)
    if name:text=f'Per «{name[1]}», la fonte riporta nome e cognome: {name[2]}.'
    match=re.fullmatch(r'Per «([^«»]+)», la fonte riporta (nome e cognome|nazionalità|nascita|morte): (.+)\.',text)
    if not match:return None
    group=next(name for name,_ in GROUPS if name.casefold()==match[2])
    pairs=re.findall(r'([a-zà-ÿ ]+) «([^«»]+)»',match[3])
    if not pairs or len(pairs)>3:return None
    allowed={'Nome e cognome':('nome','cognome'),'Nazionalità':('nazionalità',),
             'Nascita':('luogo','giorno e mese','anno'),'Morte':('luogo','giorno e mese','anno')}[group]
    # Parse separators explicitly; never ignore extra prose between fields.
    pattern=r'(nome|cognome|nazionalità|luogo|giorno e mese|anno) «([^«»]+)»'
    chunks=re.split(r', (?=[a-zà-ÿ ]+ «)| e (?=(?:nome|cognome|nazionalità|luogo|giorno e mese|anno) «)',match[3])
    fields=[];previous=-1
    for chunk in chunks:
        pair=re.fullmatch(pattern,chunk)
        if not pair or pair[1] not in allowed or not literal(pair[2]):return None
        index=allowed.index(pair[1])
        if index<=previous:return None
        previous=index;fields.append((pair[1],pair[2].casefold()))
    if not fields:return None
    return dict(predicate='source_biographic_fields',subject=match[1],group=group,
        fields=tuple(fields),statute='EXPLICIT_SOURCE_RECORD',inferred=False)
