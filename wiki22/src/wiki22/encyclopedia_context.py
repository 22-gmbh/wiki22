"""Documentary comparison and explicit temporal mentions. No semantic fusion."""
from difflib import SequenceMatcher
from collections import defaultdict, deque
import re

MAX_NOTES = 400
MAX_CHARS = 200000
MONTHS = 'gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre'.split()
ERA = r'(?:\s*(?P<era>a\s*\.\s*C\s*\.?|d\s*\.\s*C\s*\.?))?'
FULL_DATE = re.compile(r'(?<!\w)(?P<day>\d{1,2})(?:[º°o])?\s+(?P<month>'+ '|'.join(MONTHS) +r')\s+(?P<year>\d{1,4})'+ERA+r'(?!\w)',re.I)
MONTH_DATE = re.compile(r'(?<!\w)(?P<month>'+ '|'.join(MONTHS) +r')\s+(?P<year>\d{1,4})'+ERA+r'(?!\w)',re.I)
YEAR = re.compile(r'(?<![\w.,])(?P<year>[12]\d{3}|\d{1,3}(?=\s*[ad]\s*\.\s*C))'+ERA+r'(?!\w|[.,]\d)',re.I)
CENTURY = re.compile(r'\b(?P<roman>[IVX]{1,8})\s+secolo'+ERA,re.I)


def key(text):
    # Whitespace only: negation, case, numbers and punctuation are preserved.
    return ' '.join(text.split())


def bounded_notes(document):
    notes=[];size=0
    for note in document['notes']:
        if len(notes)>=MAX_NOTES or size+len(note['excerpt'])>MAX_CHARS:break
        notes.append(note);size+=len(note['excerpt'])
    return notes


def word_changes(left, right):
    a=re.findall(r'\s+|\w+|[^\w\s]',left);b=re.findall(r'\s+|\w+|[^\w\s]',right)
    if max(len(a),len(b))>800:
        return [[dict(text=left,changed=True)],[dict(text=right,changed=True)]]
    out=[[],[]]
    for tag,i,j,k,l in SequenceMatcher(None,a,b,autojunk=False).get_opcodes():
        if i!=j:out[0].append(dict(text=''.join(a[i:j]),changed=tag!='equal'))
        if k!=l:out[1].append(dict(text=''.join(b[k:l]),changed=tag!='equal'))
    return out


def compare_documents(left, right):
    a,b=bounded_notes(left),bounded_notes(right)
    rows=[];counts=dict(common=0,different=0,left_only=0,right_only=0)
    positions=defaultdict(deque)
    for i,n in enumerate(b):positions[key(n['excerpt'])].append(i)
    matches={};used=set()
    for i,n in enumerate(a):
        queue=positions[key(n['excerpt'])]
        if queue:
            index=queue.popleft();matches[i]=index;used.add(index)
    remaining=deque(i for i in range(len(b)) if i not in used)
    for i,ln in enumerate(a):
        if i in matches:rn=b[matches[i]];kind='common'
        elif remaining:rn=b[remaining.popleft()];kind='different'
        else:rn=None;kind='left_only'
        counts[kind]+=1
        changes=word_changes(ln['excerpt'],rn['excerpt']) if kind=='different' else None
        rows.append(dict(kind=kind,left=ln,right=rn,changes=changes))
    for index in remaining:
        counts['right_only']+=1;rows.append(dict(kind='right_only',left=None,right=b[index],changes=None))
    return dict(left=descriptor(left),right=descriptor(right),rows=rows,counts=counts,
        examined=[len(a),len(b)],total=[len(left['notes']),len(right['notes'])],
        limited=len(a)<len(left['notes']) or len(b)<len(right['notes']),
        method='Confronto testuale: i punti di incontro hanno lo stesso testo, salvo gli spazi. I passaggi non identici sono affiancati per ordine residuo: possono trattare fatti diversi. Le differenze non dimostrano da sole una contraddizione. Nessuna fonte viene sovrascritta.')


def descriptor(d):
    return {k:d[k] for k in ('title','library_id','library_name','article_id','source_hash','complete')}


def roman_value(value):
    # Only canonical I–XXX century notation, never arbitrary letters interpreted as dates.
    numerals=['I','II','III','IV','V','VI','VII','VIII','IX','X','XI','XII','XIII','XIV','XV','XVI','XVII','XVIII','XIX','XX','XXI','XXII','XXIII','XXIV','XXV','XXVI','XXVII','XXVIII','XXIX','XXX']
    return numerals.index(value.upper())+1 if value.upper() in numerals else None


def date_mentions(text):
    taken=[m.span() for m in re.finditer(r'\b(?:ISBN(?:-1[03])?|ISSN)\s*:?[\s0-9Xx-]+',text,re.I)];result=[]
    # Normalized web addresses are citation metadata, not historical events.
    for url in re.finditer(r'(?:https?\s*:\s*/\s*/|\b(?:[a-z]+\s*\.\s*)+(?:it|com|org)\s*/|\b(?:it|com|org)\s*/\s*(?:storia|news|sito|documents)\s*/)[^\n]*',text,re.I):
        taken.append(url.span())
    def add(m,start,end,month=0,day=0):
        if any(m.start()<b and m.end()>a for a,b in taken):return
        taken.append(m.span());result.append(dict(label=m.group().strip(),start=start,end=end,month=month,day=day,offsets=list(m.span())))
    for m in FULL_DATE.finditer(text):
        year=int(m['year']);month=MONTHS.index(m['month'].lower())+1;day=int(m['day'])
        leap=year%4==0 and (year%100!=0 or year%400==0)
        if not year or not 1<=day<=[31,29 if leap else 28,31,30,31,30,31,31,30,31,30,31][month-1]:continue
        year=-year if (m['era'] or '').lower().startswith('a') else year
        add(m,year,year,month,day)
    for m in MONTH_DATE.finditer(text):
        # An invalid complete date must not silently become a valid month date.
        if re.search(r'\d\s+$',text[max(0,m.start()-4):m.start()]):continue
        year=int(m['year'])
        if not year:continue
        year=-year if (m['era'] or '').lower().startswith('a') else year
        add(m,year,year,MONTHS.index(m['month'].lower())+1)
    for m in CENTURY.finditer(text):
        n=roman_value(m['roman'])
        if not n:continue
        start,end=(n-1)*100+1,n*100
        if (m['era'] or '').lower().startswith('a'):start,end=-end,-start
        add(m,start,end)
    for m in YEAR.finditer(text):
        year=int(m['year'])
        if not year:continue
        following=text[m.end():]
        if re.match(r'\s*(?:€|%|euro\b|abitanti\b|persone\b|soldati\b|metri\b|km\b|kg\b)',following,re.I):continue
        year=-year if (m['era'] or '').lower().startswith('a') else year
        add(m,year,year)
    return sorted(result,key=lambda r:r['offsets'])


def timeline_documents(documents, *, year=None, month=None, day=None, calendar_context=False):
    query=validate_date_filter(year,month,day)
    events=[];examined=[]
    for index,d in enumerate(documents):
        notes=bounded_notes(d);examined.append(len(notes))
        for n in notes:
            dates=calendar_mentions(n,d['title']) if calendar_context else date_mentions(n['excerpt'])
            for date in dates:
                events.append(dict(date=date,document=index,note=n,bibliographic=bool(re.search(r'\b(?:isbn|issn)\b',n['excerpt'],re.I) or re.search(r'bibliografia|riferimenti bibliografici',n['heading'],re.I))))
    events.sort(key=lambda e:(e['date']['start'],e['date']['month'],e['date']['day'],e['document'],e['note']['number']))
    total_events=len(events)
    if query['year'] is not None:events=[e for e in events if date_matches(e['date'],query)]
    return dict(documents=[descriptor(d) for d in documents],events=events,examined=examined,highlights=timeline_highlights(events),date_filter=query,total_events=total_events,
        selection_method="Selezione automatica di passaggi datati: privilegia segnali di eventi, fonti diverse e periodi diversi; privilegia le introduzioni ed esclude i riferimenti bibliografici riconosciuti. Se un passaggio contiene più date, la tappa usa la prima nel testo e conserva le altre nel contesto. Non è una graduatoria storica. Le tappe sono in ordine cronologico, a distanze grafiche uguali: non è una scala temporale proporzionale.",
        limited=any(n<len(d['notes']) for n,d in zip(examined,documents)),
        method=('Le date delle voci calendario combinano il giorno/mese della lista con l’anno del titolo, oppure l’anno della lista con il giorno/mese del titolo; la fonte resta consultabile. ' if calendar_context else '')+'Date citate nei passaggi disponibili, ordinate nel tempo. Ipotesi, negazioni e attribuzioni restano nel testo della fonte: una data citata non prova che un evento sia avvenuto. Le date implicite non sono ricostruite.')


def timeline_highlights(events, limit=12):
    """Bounded editorial heuristic, not a claim of objective historical importance.

    Keep the exact event/note, including qualifications. Cover different source
    documents and chronological regions before filling by event cues. Never use
    bibliography or duplicate the same cited passage in the panorama.
    """
    candidates=[]
    first={}
    for i,e in enumerate(events):
        # For a passage with several dates, anchor its card to its first explicit
        # date in textual order; the rest of the passage remains fully visible.
        k=(e['document'],e['note']['excerpt'])
        if e['bibliographic']:continue
        if re.search(r"\b(?:editore|citato in|hanno come fonte|pp\s*\.)",e['note']['excerpt'],re.I):continue
        if k not in first or e['date']['offsets'][0]<first[k][1]['date']['offsets'][0]:first[k]=(i,e)
    candidates=sorted(first.values())
    def score(item):
        _,e=item;t=e['note']['excerpt'].casefold();h=e['note']['heading'].casefold()
        cues=('fondat','fondaz','nacque','morì','inaugur','proclam','rivoluz','guerra','battaglia','trattato','scopert','indipenden','pubblic','approvat','costituz','unific','conquist')
        return 3*min(3,sum(c in t for c in cues))+2*int(bool(e['date']['day']))+8*int('introduzione' in h)+int(any(c in h for c in ('storia','biografia','origine')))
    chosen=[];seen=set()
    def add(item):
        i,e=item;k=(e['document'],e['note']['excerpt'])
        if k not in seen and len(chosen)<limit:chosen.append(i);seen.add(k)
    for doc in sorted({e['document'] for _,e in candidates}):
        add(max((x for x in candidates if x[1]['document']==doc),key=score))
    # Equal-sized chronological groups spread the overview without assuming
    # that ancient and modern event dates have the same precision.
    groups=min(6,len(candidates))
    for j in range(groups):
        chunk=candidates[j*len(candidates)//groups:(j+1)*len(candidates)//groups]
        add(max(chunk,key=score))
    for item in sorted(candidates,key=score,reverse=True):add(item)
    return sorted(chosen)


def validate_date_filter(year=None, month=None, day=None):
    if year is None:
        if month is not None or day is not None:raise ValueError('Scegli prima un anno.')
        return dict(year=None,month=None,day=None,label='Tutte le date')
    if type(year) is not int or not -9999<=year<=9999 or year==0:
        raise ValueError('Scegli un anno da 1 a 9999, avanti o dopo Cristo. Non esiste l’anno zero.')
    if month is not None and (type(month) is not int or not 1<=month<=12):raise ValueError('Scegli un mese valido.')
    if day is not None:
        if month is None:raise ValueError('Scegli il mese prima del giorno.')
        if type(day) is not int:raise ValueError('Scegli un giorno valido.')
        leap=abs(year)%4==0 and (abs(year)%100!=0 or abs(year)%400==0)
        maximum=[31,29 if leap else 28,31,30,31,30,31,31,30,31,30,31][month-1]
        if not 1<=day<=maximum:raise ValueError('Il giorno non esiste nel mese e anno scelti.')
    label=(str(day)+' ' if day else '')+(MONTHS[month-1]+' ' if month else '')+str(abs(year))+(' a.C.' if year<0 else '')
    return dict(year=year,month=month,day=day,label=label)


def date_matches(date, query):
    # A century/range or an unknown month/day cannot answer an exact-date query.
    return (date['start']==date['end']==query['year'] and
            (query['month'] is None or date['month']==query['month']) and
            (query['day'] is None or date['day']==query['day']))


def calendar_mentions(note,title):
    """Only explicit dated list entries in calendar articles, never free inference.

    Read the missing component from the exact article title and expose its origin.
    Never carry a date from a previous sentence, section or neighbouring bullet.
    """
    heading=note['heading'].casefold();text=note['excerpt'];out=[]
    year_title=re.fullmatch(r'(\d{1,4})(?:\s*(a\s*\.\s*C\s*\.?|d\s*\.\s*C\s*\.?))?',title,re.I)
    day_title=re.fullmatch(r'(\d{1,2})\s+('+'|'.join(MONTHS)+')',title,re.I)
    if year_title and (any(m in heading for m in MONTHS) or heading.startswith('eventi') or heading==title.casefold() or (heading=='testo' and str(note.get('source','')).startswith('file:'))):
        year=int(year_title[1])*(-1 if (year_title[2] or '').lower().startswith('a') else 1)
        pattern=re.compile(r'(?:^|\*)\s*(?P<day>\d{1,2})(?:[º°o])?\s+(?P<month>'+'|'.join(MONTHS)+r')(?!\w)(?!\s+\d{3,4}\b)',re.I)
        matches=list(pattern.finditer(text))
        for i,m in enumerate(matches):
            segment=[m.start(),matches[i+1].start() if i+1<len(matches) else len(text)]
            month=MONTHS.index(m['month'].lower())+1;day=int(m['day'])
            try:q=validate_date_filter(year,month,day)
            except ValueError:continue
            out.append(dict(label=q['label'],start=year,end=year,month=month,day=day,offsets=[m.start('day'),m.end('month')],segment=segment,context_date='Anno dal titolo «'+title+'»'))
    elif day_title and (heading.startswith('eventi') or heading==title.casefold() or (heading=='testo' and str(note.get('source','')).startswith('file:'))):
        day=int(day_title[1]);month=MONTHS.index(day_title[2].lower())+1
        pattern=re.compile(r'(?:^|\*)\s*(?P<year>\d{1,4})'+ERA+r'\s*(?=[–—−:*]|-(?!\s*\d))',re.I)
        matches=list(pattern.finditer(text))
        for i,m in enumerate(matches):
            segment=[m.start(),matches[i+1].start() if i+1<len(matches) else len(text)]
            year=int(m['year'])*(-1 if (m['era'] or '').lower().startswith('a') else 1)
            try:q=validate_date_filter(year,month,day)
            except ValueError:continue
            out.append(dict(label=q['label'],start=year,end=year,month=month,day=day,offsets=[m.start('year'),m.start('year')+len(m['year'])],segment=segment,context_date='Giorno e mese dal titolo «'+title+'»'))
    return out
