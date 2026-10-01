"""QA039: explicit source-anchored questions about relative antecedents.

Reference interpretation is distinct from asserting an event in the world.
Nested nominal attachments remain alternatives; a user choice is labeled as
an interpretation, never as independent confirmation of a fact.
"""
from dataclasses import dataclass
from copy import deepcopy
import re
from . import passage_comprehension as pc
from .participial_comprehension import ParticipialConversation

QUOTE=r'(?:«[^»]+»|“[^”]+”|"[^"]+")'
LOCATION=r'(?:\s*\((?:riga|righe)\s+[\d ,e–—-]+\))?'
@dataclass(frozen=True)
class ReferenceRequest:
    token:str
    fragment:str|None

def request(question):
    q=' '.join(question.strip().split())
    patterns=[rf'Nella frase\s+(?P<fragment>{QUOTE}){LOCATION}\s*,?\s*a (?:chi|che cosa|cosa) si riferisce\s+(?P<token>{QUOTE})\s*\?',
              rf'A (?:chi|che cosa|cosa) si riferisce\s+(?P<token>{QUOTE})(?:\s+nella frase\s+(?P<fragment>{QUOTE}))?\s*\?']
    for pattern in patterns:
        m=re.fullmatch(pattern,q,re.I)
        if m:
            token=m['token'][1:-1].strip();fragment=m['fragment']
            return ReferenceRequest(token,fragment[1:-1].strip() if fragment else None)
    return None

def normalized(text):
    chars=[];positions=[]
    for i,ch in enumerate(text):
        if ch.isspace():
            if chars and chars[-1]!=' ':chars.append(' ');positions.append(i)
        else:
            for c in ch.casefold():chars.append(c);positions.append(i)
    return ''.join(chars),positions

def occurrences(needle,text):
    hay,mapping=normalized(text);n,_=normalized(needle);n=n.strip()
    if not n:return []
    pattern=r'(?<!\w)'+re.escape(n)+r'(?!\w)'
    return [(mapping[m.start()],mapping[m.end()-1]+1) for m in re.finditer(pattern,hay)]

def relative_options(text,span):
    with pc.LOCK:sentences=pc.solver().parse(text)
    for ts in sentences:
        matched=[t for t in ts if (t.lo,t.hi)==span and 'Rel' in pc.feats(t).get('PronType','').split(',')]
        if len(matched)!=1:continue
        by_id={t.id:t for t in ts};node=matched[0];visited=set()
        while node.id not in visited:
            visited.add(node.id)
            if node.rel=='acl:relcl':break
            if node.head not in by_id:return []
            node=by_id[node.head]
        if node.rel!='acl:relcl' or node.head not in by_id:return []
        head=by_id[node.head]
        if head.pos not in {'NOUN','PROPN'}:return []
        # A nominal modifier or coordination can supply another attachment.
        # Retain full phrases; do not collapse a possessor into its head.
        heads={head.id:head}
        if head.rel in {'nmod','conj','appos'} and head.head in by_id and by_id[head.head].pos in {'NOUN','PROPN'}:heads[head.head]=by_id[head.head]
        for t in pc.nodes(ts,head):
            if t.pos in {'NOUN','PROPN'} and t.rel in {'nmod','conj','appos'}:heads[t.id]=t
        options=[];sentence_span=(min(t.lo for t in ts),max(t.hi for t in ts))
        for t in heads.values():
            lo,hi=pc.span(text,ts,t)
            if hi>span[0]:continue
            options.append(dict(value=text[lo:hi],antecedent_span=[lo,hi],sentence_span=list(sentence_span),sentence=text[sentence_span[0]:sentence_span[1]],relative_span=list(span),relative_clause_head=node.form,parsed_attachment=t.id==head.id))
        return options
    return []

class ReferenceConversation(ParticipialConversation):
    def __init__(self,lexicon):
        super().__init__(lexicon);self.reference_pending=None;self.reference_previous=None
    def _reference_result(self,question,text,source,req,options,selected=None,confirmed=False,reason=None):
        base=dict(reader='QA039',source=source,source_sha256=pc.digest(text),question=question,
                  llm_calls=0,statistical_grammar_required=True,factual_answer_authorized=False,
                  event_asserted=False,task='relative_reference',requested_token=req.token,
                  reference_options=deepcopy(options),context_used=confirmed,proofs=[],value=None)
        if selected is not None:
            base.update(status='READING',reason='USER_SELECTED_REFERENCE' if confirmed else 'STRUCTURAL_RELATIVE_REFERENCE',value=selected['value'],reference_user_confirmed=confirmed,
                        answer=('Hai scelto questa lettura: ' if confirmed else 'Nella lettura grammaticale del passaggio, ')+ '«'+req.token+'» ha come antecedente «'+selected['value']+'».\n«'+selected['sentence']+'»',proofs=[deepcopy(selected)])
        elif options:
            base.update(status='CLARIFY',reason='AMBIGUOUS_REFERENCE_ATTACHMENT',answer='Il riferimento può collegarsi a più espressioni del passaggio:\n'+'\n'.join(str(i)+'. «'+o['value']+'»' for i,o in enumerate(options,1))+'\nIndica quale lettura intendi oppure precisa il passaggio.')
        else:
            base.update(status='CLARIFY',reason=reason,answer='Non riesco ancora a stabilire questo riferimento nel testo. Indica una frase più precisa.')
        return base
    def answer(self,question,text,*,source='provided-passage',scope=None):
        if not isinstance(question,str) or not isinstance(text,str):raise ValueError('Domanda e testo devono essere stringhe.')
        if len(question)>512 or len(text)>16384:raise ValueError('Domanda o passaggio oltre il limite di lettura.')
        key=(pc.digest(text),source,deepcopy(scope));reply=' '.join(question.casefold().strip(' .!?').split())
        pending=self.reference_pending;self.reference_pending=None
        previous=self.reference_previous;self.reference_previous=None
        if previous and previous[0]==key and reply in {'come lo sai','dove lo dice','mostrami la frase','spiegati meglio','non ho capito'}:
            result=deepcopy(previous[1]);result.update(question=question,value=None,context_used=True,reason='EXPLAIN_REFERENCE_READING',answer='È una lettura del riferimento grammaticale, non una conferma che l’evento sia avvenuto.\n'+previous[1]['answer']);self.reference_previous=previous;return result
        if pending and pending['key']==key and reply in {'come lo sai','dove lo dice','mostrami la frase','spiegati meglio','non ho capito'}:
            self.reference_pending=pending
            result=self._reference_result(question,text,source,pending['request'],pending['options'])
            result.update(reason='EXPLAIN_REFERENCE_CHOICES',context_used=True)
            result['answer']+='\nLa struttura grammaticale lascia più letture; non ne confermo una.\n'+'\n'.join('«'+s+'»' for s in dict.fromkeys(o['sentence'] for o in pending['options']))
            return result
        if pending and pending['key']==key and (reply.isdecimal() or reply in {'sì','si'}):
            if reply.isdecimal() and 1<=int(reply)<=len(pending['options']):
                result=self._reference_result(question,text,source,pending['request'],pending['options'],pending['options'][int(reply)-1],True);self.reference_previous=(key,deepcopy(result));return result
            self.reference_pending=pending
            result=self._reference_result(question,text,source,pending['request'],pending['options']);result['context_used']=True;result['answer']='Serve il numero di una delle letture elencate.\n'+result['answer'];return result
        req=request(question)
        if req is None:return super().answer(question,text,source=source,scope=scope)
        # Reference tasks start their own context, never reuse an old event or
        # lexical confirmation. Source text and selection are hashed above.
        self.last=None;self.last_result=None;self.lexical_pending=None
        spans=occurrences(req.token,text)
        if req.fragment:
            fragments=occurrences(req.fragment,text)
            if len(fragments)!=1:return self._reference_result(question,text,source,req,[],reason='REFERENCE_FRAGMENT_NOT_UNIQUE')
            lo,hi=fragments[0];spans=[s for s in spans if lo<=s[0]<s[1]<=hi]
        if len(spans)!=1:return self._reference_result(question,text,source,req,[],reason='REFERENCE_TOKEN_NOT_UNIQUE')
        options=relative_options(text,spans[0])
        if not options:return self._reference_result(question,text,source,req,[],reason='REFERENCE_STRUCTURE_UNSUPPORTED')
        if len(options)>5:return self._reference_result(question,text,source,req,[],reason='REFERENCE_TOO_MANY_ALTERNATIVES')
        if len(options)>1:
            self.reference_pending=dict(key=key,request=req,options=options)
            return self._reference_result(question,text,source,req,options)
        result=self._reference_result(question,text,source,req,options,options[0]);self.reference_previous=(key,deepcopy(result));return result
