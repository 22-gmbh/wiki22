"""SEMANTICS025: explicit event roles for experimental passage dialogue.

A small declared lexicon maps grammatical perspectives to event participants.
It is not a similarity score, a learned truth classifier, or general Italian
understanding. Source spans, tense, polarity and discourse restrictions survive.
"""
from dataclasses import dataclass, replace
import re
from . import passage_comprehension as pc

# Ordered semantic roles with their surface realizations. No rule equates a
# shipment with receipt, or a purchase with physical delivery or ownership.
SCHEMAS = {
    'vendere': ('commerce', (('seller','nsubj',()),('buyer','obl',('a',)),('item','obj',()))),
    'comprare': ('commerce', (('buyer','nsubj',()),('seller','obl',('da',)),('item','obj',()))),
    'acquistare': ('acquisition', (('buyer','nsubj',()),('seller','obl',('da',)),('item','obj',()))),
    'prestare': ('loan', (('lender','nsubj',()),('borrower','obl',('a',)),('item','obj',()))),
    'ricevere': ('receipt', (('recipient','nsubj',()),('origin','obl',('da',)),('item','obj',()))),
    'spedire': ('dispatch', (('sender','nsubj',()),('destination','obl',('a',)),('item','obj',()))),
}

# Implication is directional: a sale entails a purchase/acquisition, whereas
# 'acquistare esperienza da qualcuno' does not entail a commercial transaction.
PERSPECTIVES = {('vendere','comprare'), ('vendere','acquistare'),
                ('comprare','vendere'), ('comprare','acquistare')}

@dataclass(frozen=True)
class Event:
    family: str
    participants: tuple
    circumstances: tuple
    source_frame: pc.Frame


def event(frame):
    schema=SCHEMAS.get(frame.predicate)
    if schema is None:return None
    family,slots=schema
    participants=[];assigned=set()
    for name,role,prep in slots:
        found=[(i,a) for i,a in enumerate(frame.arguments) if a.role==role and a.prep==prep]
        if len(found)>1:return None
        if found:
            i,a=found[0];assigned.add(i);participants.append((name,a))
    # Cross-perspective interpretations require all participants; otherwise a
    # missing counterpart may be mistaken for a theme or unrelated location.
    if len(participants)!=len(slots):return None
    return Event(family,tuple(participants),tuple(a for i,a in enumerate(frame.arguments) if i not in assigned),frame)


def project(ev,predicate):
    schema=SCHEMAS.get(predicate)
    if schema is None:return None
    f=ev.source_frame
    if predicate==f.predicate:return f
    if (f.predicate,predicate) not in PERSPECTIVES:return None
    # Source direction must be licensed, and every participant explicit.
    parts=dict(ev.participants)
    seller=parts.get('seller');buyer=parts.get('buyer')
    if ev.family!='commerce' or seller is None or buyer is None:return None
    if seller.key==buyer.key:return None
    # Qualified projections only explain why an answer is blocked. Negative
    # questions never use them to infer a negative answer.
    args=tuple(replace(parts[name],role=role,prep=prep) for name,role,prep in schema[1])
    trace=('event:commerce', 'perspective:'+f.predicate+'->'+predicate,
           *('role:'+name+':'+str(a.span[0])+':'+str(a.span[1]) for name,a in ev.participants))
    return replace(f,predicate=predicate,arguments=args+ev.circumstances,derivations=f.derivations+trace,scope=f.scope+(('semantic_polarity_unresolved',) if 'negative' in f.scope else ()))


def normalize_attachments(frame,text):
    """Resolve only the declared counterpart slot under a direct nominal.

UD parsers often attach 'a Giulia' to 'libro'. A named counterpart with the
schema's preposition can be reattached by verb valency, provided no competing
counterpart or non-contiguous nominal span exists. This remains a fallible
linguistic interpretation and is recorded explicitly in the derivation.
"""
    schema=SCHEMAS.get(frame.predicate)
    if schema is None:return frame
    slots=[(name,role,prep) for name,role,prep in schema[1] if role=='obl']
    if len(slots)!=1:return frame
    name,role,prep=slots[0]
    with pc.LOCK: sentences=pc.solver().parse(text)
    tokens=[ts for ts in sentences if ts and frame.span[0]<=min(t.lo for t in ts) and max(t.hi for t in ts)<=frame.span[1]]
    if len(tokens)!=1:return frame
    ts=tokens[0]
    candidates=[]
    for i,a in enumerate(frame.arguments):
        if a.role not in {'obj','nsubj'} or a.references:continue
        heads=[t for t in ts if t.rel in {'obj','nsubj','nsubj:pass'} and a.span[0]<=t.lo<t.hi<=a.span[1]]
        if len(heads)!=1:continue
        head=heads[0]
        for t in pc.children(ts,head.id):
            if t.rel=='nmod' and t.pos=='PROPN' and pc.case(ts,t)==prep:
                candidates.append((i,a,head,t))
    if not candidates:return frame
    if len(candidates)!=1 or any(a.role==role and a.prep==prep for a in frame.arguments):
        return replace(frame,scope=frame.scope+('semantic_attachment_ambiguous',))
    i,a,head,t=candidates[0]
    removed={n.id for n in pc.subtree(ts,t.id)}
    nominal=[n for n in pc.nodes(ts,head) if n.id not in removed]
    # Never manufacture a contiguous answer span containing removed content.
    if any(min(n.lo for n in nominal)<n.lo<max(n.hi for n in nominal) for n in ts if n.id in removed):
        return replace(frame,scope=frame.scope+('semantic_attachment_ambiguous',))
    reduced=pc.argument(text,[n for n in ts if n.id not in removed],head)
    counterpart=replace(pc.argument(text,ts,t),role=role,prep=prep)
    args=list(frame.arguments);args[i]=replace(reduced,role=a.role);args.append(counterpart)
    return replace(frame,arguments=tuple(args),derivations=frame.derivations+('valency_attachment:'+frame.predicate+':'+name+':'+str(t.lo)+':'+str(t.hi),))


class SemanticConversation(pc.PassageConversation):
    """Event-perspective dialogue, preserving the previous reading contract."""
    def _read_frames(self,text):
        frames,error=pc.read_frames(text)
        self.text=text
        self.pending=None
        normalized=[normalize_attachments(f,text) for f in frames]
        guarded=[]
        for f in normalized:
            ev=event(f)
            uncertain=[]
            if ev is not None:
                required={a.key for _,a in ev.participants}
                for other in normalized:
                    if other is f or other.predicate!=f.predicate or other.tense!=f.tense:continue
                    if 'negative' in other.scope and event(other) is None and required.issubset({a.key for a in other.arguments}):
                        uncertain.append(other.span)
            # A failed parse of a relevant denial is uncertainty, not permission
            # to ignore that sentence. Mention overlap may BLOCK, never prove.
            if uncertain:f=replace(f,scope=f.scope+('unresolved_negative_context',),contexts=tuple(sorted(set(f.contexts)|set(uncertain))))
            guarded.append(f)
        self.events=[e for f in guarded if (e:=event(f)) is not None]
        return guarded,error

    def _parse_question(self,question):
        # Clarification selects among existing interpretations, never invents
        # a participant. Full questions still use the grammatical parser.
        date=re.fullmatch(r'(?:nel|in|quello del|quella del)\s+(\d{4})\s*[?!.]?',question,re.I)
        if date and getattr(self,'pending',None):
            anchor=pc.Argument('obl',('in',),(date[1],),date.span(1),kind='NUM')
            return replace(self.pending,arguments=self.pending.arguments+(anchor,))
        follow=re.fullmatch(r'(?:e\s+)?(a chi|da chi)\s*[?!.]?',question,re.I)
        if follow and self.last:
            prep=('a',) if follow[1].casefold()=='a chi' else ('da',)
            return replace(self.last,wh='chi',target=('obl',prep),arguments=tuple(a for a in self.last.arguments if not(a.role=='obl' and a.prep==prep)))
        q=pc.parse_question(question)
        q=normalize_attachments(q,question) if q else None
        return None if q and 'semantic_attachment_ambiguous' in q.scope else q

    def _candidate_frames(self,question):
        result=list(self.frames)
        if question.scope:return result
        for ev in self.events:
            if ev.source_frame.predicate!=question.predicate:
                f=project(ev,question.predicate)
                if f is not None:result.append(f)
        return result

    def _remember_question(self,question,matches):
        f=matches[0][0]
        # Keep the event, including the value just answered, for role followups.
        # Argument keys/spans stay tied to the supplied text, not paraphrases.
        return replace(question,arguments=f.arguments,derivations=f.derivations)

    def answer(self,question,text,*,source='provided-passage',scope=None):
        previous=self.last
        pending_before=getattr(self,'pending',None)
        result=super().answer(question,text,source=source,scope=scope)
        result['reader']='SEMANTICS025'
        if result['reason']=='MULTIPLE_ANSWERS':
            self.pending=self._parse_question(question)
        elif result.get('reason') not in {'SIMPLIFIED_READING','EXPLAIN_PREVIOUS_READING'}:
            self.pending=None
        if pending_before is not None and result.get('value') and re.fullmatch(r'(?:nel|in|quello del|quella del)\s+\d{4}\s*[?!.]?',question,re.I):
            result['context_used']=True
        if previous is not None and self.last is not None and re.fullmatch(r'(?:e\s+)?(?:a chi|da chi)\s*[?!.]?',question,re.I):
            result['context_used']=True
        if result.get('value') and any(p.get('derivations') for p in result['proofs']):
            result['reason']='MATCHED_SEMANTIC_EVENT'
        if result.get('reason')=='SIMPLIFIED_READING' and result.get('proofs'):
            proof=result['proofs'][0]
            trace=proof.get('derivations',[])
            if 'event:commerce' in trace and not proof.get('scope'):
                roles={}
                for entry in trace:
                    if entry.startswith('role:'):
                        _,role,lo,hi=entry.split(':');roles[role]=text[int(lo):int(hi)]
                if set(roles)=={'seller','buyer','item'}:
                    result['answer']='Il testo descrive una compravendita: «'+roles['seller']+'» vende, «'+roles['buyer']+'» compra e l’oggetto è «'+roles['item']+'». La domanda chiede '+{'chi':'la persona coinvolta','cosa':'l’oggetto','quando':'il momento','anno':'l’anno'}.get(result.get('question_kind'),'il dato indicato')+': «'+proof['value']+'». Le due formulazioni descrivono lo stesso episodio, da punti di vista diversi.'
        if self.last_result is not None and result.get('reason') not in {'SIMPLIFIED_READING','EXPLAIN_PREVIOUS_READING'}:
            from copy import deepcopy
            self.last_result=deepcopy(result)
        return result


def comprehend(question,text):
    return SemanticConversation().answer(question,text)
