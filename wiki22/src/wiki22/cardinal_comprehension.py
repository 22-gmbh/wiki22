"""COUNT050: explicit cardinal modifiers of complete source noun descriptions."""
from dataclasses import replace
import re
from copy import deepcopy
from . import passage_comprehension as pc
from .manner_comprehension import MannerConversation, nominal, compatible

class CardinalConversation(MannerConversation):
 def _count_request(self,question):
  with pc.LOCK:ss=pc.solver().parse(question)
  if len(ss)!=1:return None
  ts=ss[0];root=next(t for t in ts if t.head==0)
  slots=[t for t in pc.children(ts,root.id) if t.pos=='NOUN' and any(x.rel=='det' and x.lemma=='quanto' and pc.feats(x).get('Number')=='Plur' for x in pc.children(ts,t.id))]
  if len(slots)!=1:return None
  slot=slots[0];branch=pc.subtree(ts,slot.id)
  quantifiers=[x for x in pc.children(ts,slot.id) if x.rel=='det' and x.lemma=='quanto']
  # Preserve all noun restrictions; a cardinal request is not a generic object.
  if any(t.id!=slot.id and t.rel not in {'det','amod','nmod','case','compound','flat','flat:name'} for t in branch):return None
  if any(t.pos=='NUM' for t in branch) or any(t.lemma in pc.NEG|pc.MODAL for t in ts):return None
  kept=[t for t in branch if t not in quantifiers]
  return dict(slot=pc.argument(question,kept,slot),text=question,tokens=ts,head=slot)
 def _parse_question(self,question):
  q=super()._parse_question(question)
  if q is None:return None
  request=self._count_request(question)
  if request is None:
   with pc.LOCK:sentences=pc.solver().parse(question)
   intent=any(t.rel=='det' and t.lemma=='quanto' and pc.feats(t).get('Number')=='Plur' for ts in sentences for t in ts)
   return None if intent else q
  if q.scope:return None
  return replace(q,wh='cosa',derivations=q.derivations+('explicit_cardinal_request',))
 def _candidate_frames(self,question):
  frames=super()._candidate_frames(question)
  if 'explicit_cardinal_request' not in question.derivations:return frames
  request=self._count_request(self.current_question)
  if request is None:return []
  with pc.LOCK:sentences=pc.solver().parse(self.text)
  expected=request['slot'];filtered=[]
  for f in frames:
   if f.predicate!=question.predicate:continue
   targets=[a for a in f.arguments if (a.role,a.prep)==question.target]
   if len(targets)!=1:continue
   target=targets[0];matches=[]
   for ts in sentences:
    if not(f.span[0]<=min(t.lo for t in ts) and max(t.hi for t in ts)<=f.span[1]):continue
    for head in ts:
     if head.pos!='NOUN' or not(target.span[0]<=head.lo<head.hi<=target.span[1]):continue
     cs=pc.children(ts,head.id);nums=[x for x in cs if x.rel=='nummod' and x.pos=='NUM']
     if len(nums)!=1:continue
     num=nums[0]
     if not re.fullmatch(r'[0-9]+(?:[.,][0-9]+)*|[^\W\d_]+',num.form):continue
     if pc.feats(num).get('NumType') not in {None,'Card'} or num.lo>=head.lo or len(pc.subtree(ts,num.id))!=1:continue
     if any(t.rel=='det' and pc.feats(t).get('Definite') not in {'Def'} for t in cs):continue
     branch=pc.subtree(ts,head.id)
     if any(t.id not in {head.id,num.id} and t.rel not in {'det','amod','nmod','case','compound','flat','flat:name'} for t in branch):continue
     kept=[t for t in branch if t.id!=num.id]
     a=replace(pc.argument(self.text,kept,head),role=expected.role,prep=expected.prep)
     if not pc.compatible(expected,a):continue
     # The numeric token must belong to this full argument, not a nested owner.
     if pc.key(ts,head)!=target.key:continue
     # Bound participants retain determiner meaning, not merely lemma overlap.
     valid=True
     for wanted in question.arguments:
      bound=[b for b in f.arguments if pc.compatible(wanted,b)]
      if not bound:valid=False;break
      qhead=next((t for t in request['tokens'] if wanted.span[0]<=t.lo<t.hi<=wanted.span[1] and t.rel in {'nsubj','nsubj:pass','obj','iobj','obl','obl:agent','nummod'}),None)
      shead=next((t for t in ts if any(b.span[0]<=t.lo<t.hi<=b.span[1] for b in bound) and t.rel in {'nsubj','nsubj:pass','obj','iobj','obl','obl:agent','nummod'}),None)
      if qhead is None or shead is None:valid=False;break
      qa=nominal(request['text'],request['tokens'],qhead);sa=nominal(self.text,ts,shead)
      if qa is None or sa is None or not compatible(qa,sa):valid=False;break
     if valid:matches.append(num)
   if len(matches)!=1:continue
   number=matches[0]
   newtarget=replace(target,span=(number.lo,number.hi))
   filtered.append(replace(f,arguments=tuple(newtarget if a is target else a for a in f.arguments),derivations=f.derivations+('explicit_cardinality:'+str(target.span[0])+':'+str(target.span[1]),)))
  return filtered
 def _remember_question(self,question,matches):
  remembered=super()._remember_question(question,matches)
  if 'explicit_cardinal_request' not in question.derivations:return remembered
  spans=[tuple(map(int,d.split(':')[1:])) for d in matches[0][0].derivations if d.startswith('explicit_cardinality:')]
  # The answer is a number, but later turns still refer to the whole group.
  return replace(remembered,arguments=tuple(replace(a,span=span) if (span:=next((s for s in spans if s[0]<=a.span[0]<a.span[1]<=s[1]),None)) else a for a in remembered.arguments))
 def answer(self,*args,**kwargs):
  result=super().answer(*args,**kwargs)
  if any(any(d.startswith('explicit_cardinality:') for d in p.get('derivations',[])) for p in result.get('proofs',[])):
   result['reader']='COUNT050';result['quantity_inferred']=False;result['task']='explicit_source_cardinality'
   text=args[1] if len(args)>1 else kwargs['text']
   for p in result['proofs']:
    spans=[tuple(map(int,d.split(':')[1:])) for d in p.get('derivations',[]) if d.startswith('explicit_cardinality:')]
    if len(spans)==1:p['counted_phrase_span']=list(spans[0]);p['counted_phrase']=text[slice(*spans[0])]
   multiple=len({tuple(p['sentence_span']) for p in result['proofs']})>1 or any(sum(f.predicate==p['predicate'] and tuple(f.span)==tuple(p['sentence_span']) for f in self.frames)>1 for p in result['proofs'])
   if result.get('value') is not None and multiple:
    result.update(value=None,status='CLARIFY',reason='COUNT_EPISODE_AMBIGUITY',answer='Il testo descrive più episodi: non tratto il numero di uno solo come un totale. Precisa a quale episodio ti riferisci.\n'+'\n'.join('«'+p['sentence']+'»' for p in result['proofs']))
    self.last=None;self.last_result=deepcopy(result)
  return result
