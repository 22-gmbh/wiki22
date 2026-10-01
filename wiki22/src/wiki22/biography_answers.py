"""Natural, reversible Italian realization of already-reflected Bio source roles.

Approximate/qualified values retain the existing literal wording. Exact age
calculation is explicitly derived from two source dates, not a cached fact.
"""
from datetime import date
import re

MONTHS={name:i for i,name in enumerate(('gennaio','febbraio','marzo','aprile','maggio','giugno','luglio','agosto','settembre','ottobre','novembre','dicembre'),1)}

def exact_date(fields):
    fields=dict(fields);year=fields.get('anno','');daymonth=fields.get('giorno e mese','')
    if not re.fullmatch(r'[1-9][0-9]{0,3}',year):return None
    match=re.fullmatch(r'([1-9]|[12][0-9]|3[01]) ([a-z]+)',daymonth)
    if not match or match[2] not in MONTHS:return None
    try:return date(int(year),MONTHS[match[2]],int(match[1]))
    except ValueError:return None

def realize(plan,claims):
    props=[c['proposition'] for c in claims]
    if not props or any(p['subject']!=props[0]['subject'] for p in props):return None
    title=props[0]['subject'];groups={p['group']:p for p in props}
    if plan['intent']=='età_morte':
        if not {'Nascita','Morte'}<=groups.keys():return None
        event_claims=[c for c in claims if c['proposition']['group'] in {'Nascita','Morte'}]
        bindings={(c.get('source',{}).get('evidence_id'),c.get('source',{}).get('source_binding')) for c in event_claims}
        if len(bindings)!=1 or any(not x for pair in bindings for x in pair):return None
        birth=exact_date(groups['Nascita']['fields']);death=exact_date(groups['Morte']['fields'])
        if birth is None or death is None or death<birth or death>date.today():return None
        age=death.year-birth.year-int((death.month,death.day)<(birth.month,birth.day))
        # Independent interval check: this birthday has occurred, the next has
        # not. Leap-day anniversaries follow the explicit month/day comparison.
        observed=(death.year,death.month,death.day)
        if not (birth.year+age,birth.month,birth.day)<=observed<(birth.year+age+1,birth.month,birth.day):
            raise ValueError('Age derivation failed independent interval control')
        text=f'Dalle date riportate nella fonte, {title} morì a {age} anni.'
        match=re.fullmatch(r'Dalle date riportate nella fonte, (.+) morì a ([0-9]+) anni\.',text)
        if not match or match[1]!=title or int(match[2])!=age:raise ValueError('Age realization changed the derived result')
        return text,dict(kind='DERIVED_FROM_TWO_EXACT_SOURCE_DATES',birth=birth.isoformat(),death=death.isoformat(),age=age,
            controller='BIRTHDAY_INTERVAL_CHECK',calendar_convention='MONTH_DAY_ANNIVERSARY_COMPARISON')
    event='Nascita' if plan['intent'].startswith('nascita_') else 'Morte' if plan['intent'].startswith('morte_') else None
    if event is None or event not in groups:return None
    prop=groups[event];fields=dict(prop['fields']);verb='nacque' if event=='Nascita' else 'morì'
    intent=plan['intent'].split('_',1)[1];selected={}
    if intent=='anno':
        value=fields.get('anno','')
        if not re.fullmatch(r'[1-9][0-9]{0,3}',value):return None
        phrase='nel '+value;selected={'anno':value}
    elif intent=='tempo':
        value=exact_date(prop['fields'])
        if value is not None:
            phrase='il '+fields['giorno e mese']+' '+fields['anno'];selected={k:fields[k] for k in ('giorno e mese','anno')}
        elif set(fields)&{'giorno e mese','anno'}=={'anno'} and re.fullmatch(r'[1-9][0-9]{0,3}',fields['anno']):
            phrase='nel '+fields['anno'];selected={'anno':fields['anno']}
        else:return None
    elif intent=='luogo':
        place=fields.get('luogo','')
        if not re.fullmatch(r"[^\W\d_]+(?:[ '\-][^\W\d_]+)*",place):return None
        from .biographic_articles import display_value
        phrase='a '+display_value('luogo',place);selected={'luogo':place}
    else:return None
    text=f'Secondo la fonte, {title} {verb} {phrase}.'
    # Parse the *output*, then check its recovered field values independently
    # against the reflected proposition. No qualification may be discarded.
    pattern=r'Secondo la fonte, (.+) (nacque|morì) (?:nel ([0-9]+)|il ([0-9]+ [a-z]+) ([0-9]+)|a (.+))\.'
    match=re.fullmatch(pattern,text)
    if not match or match[1]!=title or match[2]!=verb:raise ValueError('Biographic realization not reversible')
    recovered=({'anno':match[3]} if match[3] else {'giorno e mese':match[4],'anno':match[5]} if match[4] else {'luogo':match[6].casefold()})
    if recovered!=selected or any(fields.get(k)!=v for k,v in recovered.items()):raise ValueError('Biographic output changed source fields')
    return text,dict(kind='SOURCE_FIELDS_NATURAL_REALIZATION',group=event,fields=selected,controller='INDEPENDENT_OUTPUT_FIELD_PARSE')
