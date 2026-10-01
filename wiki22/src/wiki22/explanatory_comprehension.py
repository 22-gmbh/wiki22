"""EXPLANATION052: complete explanation requests and explicit source links.

A purpose is quoted as a purpose, never projected as an accomplished event.
Unknown scope, event roles and unsupported request modifiers remain constraints.
"""
from dataclasses import replace
from copy import deepcopy
import re
from . import passage_comprehension as pc
from .cardinal_comprehension import CardinalConversation
from .manner_comprehension import nominal,compatible

WRAPPER=re.compile(r'^(spiegami|spiega|vorrei sapere)\s+((?:perché|perche|per quale|con quale|a quale)\b.+)$',re.I|re.S)

class ExplanationConversation(CardinalConversation):
 def _parse_question(self,question):
  wrapper=WRAPPER.fullmatch(question.strip());body=wrapper[2] if wrapper else question;offset=question.index(body)
  q=super()._parse_question(body)
  if q is None:return None
  kind='any' if q.wh=='perché' else None
  if q.wh in {'motivo','ragione','causa','scopo'}:
   with pc.LOCK:ss=pc.solver().parse(body)
   if len(ss)!=1:return None
   ts=ss[0];root=next(t for t in ts if t.head==0)
   slots=[t for t in pc.children(ts,root.id) if t.lemma==q.wh and pc.case(ts,t) in {('per',),('con',),('a',)}]
   if len(slots)!=1:return None
   slot=slots[0];branch=pc.subtree(ts,slot.id)
   if pc.feats(slot).get('Number')!='Sing':return None
   if len(branch)!=3 or not any(t.lemma=='quale' and pc.feats(t).get('PronType')=='Int' for t in branch):return None
   if q.wh!='scopo' and pc.case(ts,slot)!=('per',):return None
   kind='purpose' if q.wh=='scopo' else 'cause' if q.wh=='causa' else 'any'
   q=replace(q,wh='perché',target=('advmod',()))
  if wrapper and kind is None:return None
  if kind:
   q=replace(q,derivations=q.derivations+('explanation_request:'+kind,))
   if wrapper:
    shift=lambda s:(s[0]+offset,s[1]+offset)
    q=replace(q,arguments=tuple(replace(a,span=shift(a.span),references=tuple(shift(s) for s in a.references)) for a in q.arguments),span=(0,len(question)),derivations=q.derivations+('explicit_explanation_wrapper:'+wrapper[1].casefold(),))
  return q
 def _bound_arguments_match(self,q,f,question_tokens,source_tokens,question_text):
  # Complete nominal participants, including their determiners, must match.
  for wanted in q.arguments:
   bound=[a for a in f.arguments if pc.compatible(wanted,a)]
   if not bound:return False
   if wanted.role=='reflexive':continue
   qheads=[t for t in question_tokens if wanted.span[0]<=t.lo<t.hi<=wanted.span[1] and t.rel in {'nsubj','nsubj:pass','obj','iobj','obl','obl:agent','nummod'}]
   sheads=[t for t in source_tokens if any(a.span[0]<=t.lo<t.hi<=a.span[1] for a in bound) and t.rel in {'nsubj','nsubj:pass','obj','iobj','obl','obl:agent','nummod'}]
   if len(qheads)!=1 or len(sheads)!=1:return False
   a=nominal(question_text,question_tokens,qheads[0]);b=nominal(self.text,source_tokens,sheads[0])
   if a is None or b is None or not compatible(a,b):return False
  return bool(q.arguments)
 def _candidate_frames(self,q):
  frames=super()._candidate_frames(q)
  if q.wh!='perché':return frames
  bound_text=getattr(self,'_explanation_confirmed_text',None) if getattr(self,'_confirmed_frame',None) is not None else None
  bound_text=bound_text or self.current_question
  with pc.LOCK:qs=pc.solver().parse(bound_text);ss=pc.solver().parse(self.text)
  if len(qs)!=1:return frames
  kind=next((x.split(':',1)[1] for x in q.derivations if x.startswith('explanation_request:')),'any')
  contextual=bool(self.last and re.fullmatch(r'(?:[Ee]\s+)?perché\s*[?!.]?',self.current_question.strip(),re.I))
  by_span={(min(t.lo for t in ts),max(t.hi for t in ts)):ts for ts in ss};out=[]
  for f in frames:
   ts=by_span.get(f.span)
   if ts is None or f.predicate!=q.predicate:out.append(f);continue
   root=next(t for t in ts if t.head==0)
   if root.pos!='VERB' or root.lemma!=f.predicate or not self._bound_arguments_match(q,f,ts if contextual else qs[0],ts,self.text if contextual else bound_text):
    guarded=kind!='any' or any(d.startswith('explanation_request:') for d in q.derivations)
    out.append(replace(f,arguments=tuple(a for a in f.arguments if a.role!='cause')) if guarded else f);continue
   cs=pc.children(ts,root.id);links=[];unrecognized=False;extra_scope=[]
   for child in cs:
    relation=None;branch=None
    if child.rel=='advcl':
     marks=[t for t in pc.children(ts,child.id) if t.rel=='mark'];mark_words=tuple(t.lemma for t in marks)
     if mark_words==('per',) and pc.feats(child).get('VerbForm')=='Inf':relation='purpose'
     elif mark_words in {('poiché',),('siccome',)}:relation='cause'
     elif mark_words==('perché',):relation='explanation'
     else:unrecognized=True;continue
     branch=pc.subtree(ts,child.id)
     if any(t.lemma in pc.NEG and t.lo<min(m.lo for m in marks) for t in branch):
      unrecognized=True;extra_scope.append('denied_explanation');continue
     if relation=='purpose' and any(t.rel in {'conj','parataxis'} and (pc.feats(t).get('VerbForm')=='Fin' or any(pc.feats(x).get('VerbForm')=='Fin' for x in pc.children(ts,t.id) if x.rel.startswith('aux'))) for t in branch):
      extra_scope.append('purpose_coordination_unresolved')
    elif child.rel=='obl' and child.lemma=='causa' and pc.case(ts,child)==('a',):
     parts=pc.children(ts,child.id);owners=[t for t in parts if t.rel=='nmod' and pc.case(ts,t)==('di',)]
     if len(owners)!=1 or any(t.rel not in {'case','nmod'} for t in parts):continue
     branch=pc.subtree(ts,child.id);relation='cause'
    if relation is None:continue
    branch=[t for t in branch if t.pos!='PUNCT'];lo=min(t.lo for t in branch);hi=max(t.hi for t in branch)
    if any(lo<=t.lo<t.hi<=hi and t not in branch and t.pos!='PUNCT' for t in ts):unrecognized=True;continue
    links.append((relation,(lo,hi)))
   args=list(f.arguments);derivations=list(f.derivations)
   # Keep old causal links, annotate recognized ones and add only new spans.
   for relation,span in links:
    if kind!='any' and kind!=relation:continue
    if not any(a.role=='cause' and a.span==span for a in args):args.append(pc.Argument('cause',(),(),span))
    derivations.append('explicit_explanation:'+relation+':'+str(span[0])+':'+str(span[1]))
   if kind!='any':
    allowed={span for relation,span in links if relation==kind}
    args=[a for a in args if a.role!='cause' or a.span in allowed]
   flags=f.scope+tuple(extra_scope)
   if links and not unrecognized and any(t.rel=='advcl' for t in cs):flags=tuple(s for s in flags if s!='subordinate_scope')
   out.append(replace(f,arguments=tuple(args),scope=flags,derivations=tuple(derivations)))
  return out
 def _remember_question(self,question,matches):
  remembered=super()._remember_question(question,matches)
  if any(d.startswith('explicit_explanation:') for d in matches[0][0].derivations):
   remembered=replace(remembered,arguments=tuple(a for a in remembered.arguments if a.role!='cause'))
  return remembered
 def answer(self,question,text,*,source='provided-passage',scope=None):
  if not isinstance(question,str) or not isinstance(text,str):raise ValueError('Domanda e testo devono essere stringhe.')
  if len(question)>512 or len(text)>16384:raise ValueError('Question/source budget exceeded')
  q=self._parse_question(question)
  if q and any(d.startswith('explicit_explanation_wrapper:') for d in q.derivations) and any(a.role=='nsubj' and a.kind in {'NOUN','PROPN'} for a in q.arguments) and self.source_hash is not None and (self.source_hash,self.scope,getattr(self,'selection',None))!=(pc.digest(text),source,scope):
   # A complete wrapped request names its own subject; no stale ellipsis is used.
   self.last=None;self.last_result=None;self.source_hash=None;self.frames=[]
  pending=getattr(self,'lexical_pending',None)
  self._explanation_confirmed_text=pending['question'] if pending and pending['key']==(pc.digest(text),source,scope) else None
  try:result=super().answer(question,text,source=source,scope=scope)
  finally:self._explanation_confirmed_text=None
  kinds=set()
  for p in result.get('proofs',[]):
   matches=[d.split(':') for d in p.get('derivations',[]) if d.startswith('explicit_explanation:')]
   for parts in matches:
    if list(map(int,parts[2:]))==p['answer_span']:
     p['explanation_kind']=parts[1];p['embedded_event_asserted']=False;kinds.add(parts[1])
  if kinds:
   result['reader']='EXPLANATION052';result['explanation_kinds']=sorted(kinds);result['embedded_event_asserted']=False
   if result.get('value') is not None:
    label='Lo scopo indicato nel testo è: ' if kinds=={'purpose'} else 'La spiegazione indicata nel testo è: '
    result['answer']=label+result['value'].rstrip('. ')+'.\n'+'\n'.join('«'+s+'»' for p in result['proofs'] for s in p.get('context_sentences',[])+[p['sentence']])
   if self.last_result is not None:self.last_result=deepcopy(result)
  return result
