"""Controlled product successor of the retained MEMIDX research extractor.

Only complete, independently asserted sentences produce semantic graph
features. Raw observed terms and canonical source metadata remain explorable.
Category labels derived here mean types explicitly mentioned in the text,
not recovered Wikipedia categories.
"""
from dataclasses import asdict
import re
from .grounding import sentences
from .propositions import parse_candidate, compatible, entity
from .memidx_candidate import DeterministicExtractor, digest

VERSION='MEMIDX001-EVIDENCE-EXTRACTOR-02'
TYPE_LABELS={
 'persona':'Persone','città':'Città','comune':'Comuni','paese':'Paesi','stato':'Stati',
 'regione':'Regioni','provincia':'Province','fiume':'Fiumi','lago':'Laghi','isola':'Isole',
 'montagna':'Montagne','vulcano':'Vulcani','specie':'Specie','pianta':'Piante','animale':'Animali',
 'organizzazione':'Organizzazioni','società':'Società','azienda':'Aziende','opera':'Opere',
 'romanzo':'Romanzi','film':'Film','album':'Album','lingua':'Lingue','concetto':'Concetti',
 'teorema':'Teoremi','struttura':'Strutture','sistema':'Sistemi'}
UNRESOLVED=re.compile(r"\b(?:forse|probabilmente|presumibilmente|potrebbe|potrebbero|sarebbe|sarebbero|avrebbe|dovrebbe|afferma|sostiene|secondo|se|qualora|questo|questa|quello|quella|egli|ella|esso|essa|essi|esse|ciò|cio)\b",re.I)


def safe_sentence(sentence):
    if not sentence.endswith('.') or len(sentence)>1800 or sentence.startswith(('*','-','«','"')):
        return False
    if UNRESOLVED.search(sentence) or re.search(r'[{}\[\]|=<>?]',sentence):
        return False
    prop=parse_candidate(sentence)
    if prop:
        if prop.predicate.startswith('property_of:'):
            direct=re.split(r'\s+(?:non\s+)?(?:è|era|fu|sarà)\s+',sentence,maxsplit=1,flags=re.I)
            if prop.modifiers or len(prop.subject.split())>6 or len(prop.object.split())>5:
                return False
            if len(direct)!=2 or entity(direct[0])!=prop.object:
                return False
            if re.search(r'\b(?:e|o|considerat[oa]|stat[oa]|completat[oa])\b',prop.subject+' '+prop.object,re.I):
                return False
        return prop.certain and compatible(prop,prop).accepted
    # The historical research grammar has three additional explicit relation
    # forms and aliases; preserve them only for plain unqualified arguments.
    extra=re.fullmatch(r'(.+?)\s+(?:nacque\s+a|è\s+parte\s+di|è\s+membro\s+di|è\s+anche\s+chiamat[oa])\s+(.+?)(?:\s+nel\s+\d{4})?[ .]*',sentence,re.I)
    if not extra:return False
    return not bool(re.search(r"[,;!?]|\b(?:non|mai|nessuno|che|quando|perché|ma)\b",extra[1]+' '+extra[2],re.I))


class EvidenceGraphExtractor(DeterministicExtractor):
    version=VERSION

    def extract(self,article):
        raw=super().extract(article)
        safe_rows=[]
        for row in article['evidence']:
            # Spaces retain the original source offsets of accepted sentences.
            chars=[' ']*len(row['text'])
            for sentence,start,end in sentences(row['text']):
                if safe_sentence(sentence):chars[start:end]=sentence
                elif end>start:chars[end-1]='.'
            safe_rows.append(dict(row,text=''.join(chars)))
        filtered=super().extract(dict(article,evidence=safe_rows))
        for original,current,evidence in zip(raw['records'],filtered['records'],article['evidence']):
            current['content_sha256']=original['content_sha256']
            current['features']=[f for f in current['features'] if f[0]!='TEMA']+[f for f in original['features'] if f[0]=='TEMA']
            categories=[];edges=list(current['edges'])
            for sentence,start,end in sentences(evidence['text']):
                if not safe_sentence(sentence):continue
                prop=parse_candidate(sentence)
                if not prop or prop.predicate!='definition_of' or prop.polarity!='positive':continue
                match=re.match(r"^(?:un[ao]?\s+|un['’])([\wà-ÿ]+)\b",prop.object,re.I)
                head=match[1].casefold() if match else ''
                if head not in TYPE_LABELS:continue
                key='TIPO_CITATO:'+head
                categories.append(['CATEGORIA',key,'Tipi citati: '+TYPE_LABELS[head],
                    dict(rule='TIPO_DICHIARATO_NEL_TESTO',subject=prop.subject,span=[start,end])])
                edges.append((('CATEGORIA',key),('ENTITÀ',prop.subject),'tipo_citato'))
            if categories:
                current['features']=[f for f in current['features'] if not(f[0]=='CATEGORIA' and f[1]=='UNKNOWN_CATEGORY')]
                # Same type may be observed repeatedly; preserve all source spans
                # without creating duplicate node identities.
                by_key={}
                for feature in categories:
                    old=by_key.setdefault(feature[1],feature)
                    spans=old[3].setdefault('spans',[])
                    if feature[3]['span'] not in spans:spans.append(feature[3]['span'])
                current['features'].extend(by_key.values())
            current['features'].sort(key=lambda f:(f[0],f[1],f[2]))
            current['edges']=sorted(set(tuple((tuple(a),tuple(b),role)) for a,b,role in edges))
        return filtered
