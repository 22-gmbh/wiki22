"""NAMING045: explicit source naming and evidence-bound identity in dialogue.

Experimental comprehension API. Keeps frozen readers unchanged and requires
no LLM, extra parser, training weights or runtime network access.
"""
from . import passage_comprehension as _pc
from .reference_comprehension import ReferenceConversation as _Base
from dataclasses import replace
import re

def build_naming_class(Base,pc,reader):
 def sentence_for(f,sentences):
  return next((s for s in sentences if (min(t.lo for t in s),max(t.hi for t in s))==f.span),None)
 def nominal_head(a,ts,text):
  for t in ts:
   if t.pos not in {'NOUN','PROPN','PRON'}:continue
   context=ts
   if any(c.rel=='cop' for c in pc.children(ts,t.id)):
    excluded={c.id for c in pc.children(ts,t.id) if c.rel not in {'amod','nmod','det','case','flat','flat:name','compound'}}
    context=[x for x in ts if x.id not in excluded]
   if pc.span(text,context,t)==a.span and pc.key(context,t)==a.key:return t
  return None
 def unwrap_name(a,ts,text):
  head=nominal_head(a,ts,text)
  if head is None or head.lemma!='nome':return None
  cs=pc.children(ts,head.id);mods=[t for t in cs if t.rel=='nmod' and pc.case(ts,t)==('di',)]
  if len(mods)!=1 or any(t not in mods and not(t.rel=='det' and pc.feats(t).get('PronType')=='Art') for t in cs):return None
  out=pc.argument(text,ts,mods[0]);return replace(out,role='nsubj',prep=())
 def feature_compatible(a,b):
  af,bf=dict(a.features),dict(b.features)
  return all(not(af.get(k) and bf.get(k) and af[k]!=bf[k]) for k in ('Gender','Number'))
 def complete_nominal(a,ts,text):
  h=nominal_head(a,ts,text)
  return h is not None and not any(t.id!=h.id and t.rel.split(':')[0] in pc.CLAUSE for t in pc.subtree(ts,h.id))
 def definite(a,ts,text):
  t=nominal_head(a,ts,text)
  return t is not None and any(x.rel=='det' and pc.feats(x).get('Definite')=='Def' for x in pc.children(ts,t.id))
 class NamingConversation(Base):
  def _parse_question(self,question):
   q=super()._parse_question(question)
   if q is None:return None
   sentences=reader.parse(question)
   if len(sentences)!=1:return q
   ts=sentences[0]
   if q.predicate=='@copula' and q.wh in {'cosa','quale'} and q.target==('predicate',()) and len(q.arguments)==1:
    a=unwrap_name(q.arguments[0],ts,question)
    if a:return replace(q,predicate='@name',arguments=(a,),wh='cosa',target=('name',()),derivations=q.derivations+('request:explicit_name',))
   if q.predicate=='chiamare' and q.wh=='come':
    root=next(t for t in ts if t.head==0);cs=pc.children(ts,root.id)
    reflexive=any(t.lemma=='si' and t.rel in {'expl','expl:pv'} for t in cs)
    passive=any(t.rel=='aux:pass' for t in cs)
    if reflexive or passive:
     roles='obj' if passive else 'nsubj'
     if sum(a.role==roles for a in q.arguments)!=1:return q
     args=tuple(replace(a,role='nsubj') if a.role==roles else a for a in q.arguments if a.role!='reflexive')
     return replace(q,predicate='@name',arguments=args,wh='cosa',target=('name',()),derivations=q.derivations+('request:naming_verb',))
   return q

  def _read_frames(self,text):
   frames,error=super()._read_frames(text)
   if error:return frames,error
   sentences=reader.parse(text);extra=[]
   for f in frames:
    ts=sentence_for(f,sentences)
    if ts is None:continue
    subjects=[a for a in f.arguments if a.role=='nsubj'];predicates=[a for a in f.arguments if a.role=='predicate']
    entity=name=None;kind=None;scopes=f.scope
    if f.predicate=='@copula' and len(subjects)==len(predicates)==1:
     sub,pred=subjects[0],predicates[0]
     if pred.kind=='PROPN' and (unwrap_name(sub,ts,text) is not None or sub.kind=='PROPN' or definite(sub,ts,text)):
      entity=unwrap_name(sub,ts,text) or sub;name=pred;kind='copular_named_identity'
     elif sub.kind=='PROPN' and definite(pred,ts,text):entity=replace(pred,role='nsubj');name=sub;kind='definite_copular_named_identity'
    elif f.predicate=='chiamare':
     roots=[t for t in ts if t.pos=='VERB' and t.lemma=='chiamare' and pc.tense(ts,t)==f.tense]
     if len(roots)!=1:continue
     root=roots[0];cs=pc.children(ts,root.id)
     names=[t for t in cs if t.rel=='xcomp' and t.pos=='PROPN']
     reflexive=any(t.lemma=='si' and t.rel in {'expl','expl:pv'} for t in cs)
     passive=any(t.rel=='aux:pass' for t in cs)
     entity_args=[a for a in f.arguments if a.role==('obj' if passive else 'nsubj')]
     if len(names)!=1 or not(reflexive or passive) or len(entity_args)!=1:continue
     name_token=names[0]
     if any(t.rel in {'ccomp','parataxis'} or t.rel=='xcomp' and t.id!=name_token.id for t in cs):continue
     if any(t.pos in {'VERB','AUX','PRON'} for t in pc.subtree(ts,name_token.id)):continue
     entity=replace(entity_args[0],role='nsubj');name=pc.argument(text,ts,name_token);kind='explicit_naming_verb'
     scopes=tuple(s for s in scopes if s!='embedded_scope')
     if passive and any(t.rel=='obl:agent' for t in cs):scopes+=('attributed_name',)
    if entity is None or name is None or entity.key==name.key:continue
    if not complete_nominal(entity,ts,text) or not complete_nominal(name,ts,text):continue
    # Only the explicit name + entity are projected. Other source arguments
    # constrain the naming relation and survive as qualifications.
    extra_args=[a for a in f.arguments if a.role not in {'nsubj','obj','predicate','reflexive'}]
    if extra_args:scopes+=('restricted_name',)
    extra.append(replace(f,predicate='@name',arguments=(replace(entity,role='nsubj',prep=()),replace(name,role='name',prep=())),scope=scopes,derivations=f.derivations+('naming:'+kind,)))
   named_spans={f.span for f in extra}
   self.unresolved_naming_keys=set()
   for f in frames:
    if f.predicate!='chiamare' or f.span in named_spans:continue
    ts=sentence_for(f,sentences)
    if any(a.role=='reflexive' for a in f.arguments) or ts and any(t.rel=='aux:pass' for t in ts):
     self.unresolved_naming_keys.update(a.key for a in f.arguments if a.role!='reflexive')
   return frames+extra,error

  def _candidate_frames(self,question):
   frames=super()._candidate_frames(question)
   if question.predicate=='@name':
    # Identical complete written nominal phrases cannot become different just
    # because a fallible lemmatizer predicts figlia/figlio in different slots.
    # Preserve raw parses; record literal alignment only for this full request.
    projected=[]
    for f in frames:
     args=list(f.arguments);changed=False
     for i,a in enumerate(args):
      for wanted in question.arguments:
       if a.role!=wanted.role or a.prep!=wanted.prep or a.key==wanted.key:continue
       lhs=' '.join(self.text[slice(*a.span)].casefold().split())
       rhs=' '.join(self.current_question[slice(*wanted.span)].casefold().split())
       if lhs and lhs==rhs:
        args[i]=replace(a,key=wanted.key);changed=True
     if any(a.role==w.role and a.prep==w.prep and a.key==w.key and not feature_compatible(a,w) for a in args for w in question.arguments):continue
     projected.append(replace(f,arguments=tuple(args),derivations=f.derivations+('literal_complete_nominal_alignment',)) if changed else f)
    return projected
   if question.tense!='present':return frames
   links=[];blocked=set(getattr(self,'unresolved_naming_keys',()))
   naming=[f for f in self.frames if f.predicate=='@name']
   for f in naming:
    a,b=f.arguments
    if f.scope or f.tense!='present':blocked.update([a.key,b.key]);continue
    links.append((a,b,f))
   peers={}
   for a,b,f in links:
    peers.setdefault(a.key,set()).add(b.key);peers.setdefault(b.key,set()).add(a.key)
   usable=[(a,b,f) for a,b,f in links if a.key not in blocked and b.key not in blocked and len(peers[a.key])==len(peers[b.key])==1]
   projected=[]
   for f in frames:
    if f.predicate=='@name' or f.tense!='present':continue
    args=list(f.arguments);contexts=set(f.contexts);trace=[]
    for i,actual in enumerate(args):
     for wanted in question.arguments:
      if actual.role!=wanted.role or actual.prep!=wanted.prep or actual.key==wanted.key:continue
      matches=[(a,b,link) for a,b,link in usable if (a.key==wanted.key and b.key==actual.key and feature_compatible(a,wanted) and feature_compatible(b,actual)) or (b.key==wanted.key and a.key==actual.key and feature_compatible(b,wanted) and feature_compatible(a,actual))]
      if not matches:continue
      for a,b,link in matches:
       contexts.add(link.span);trace.append('explicit_named_identity:'+str(link.span[0])+':'+str(link.span[1]))
      # Keep source answer span and actual role; only the identity key changes.
      args[i]=replace(actual,key=wanted.key,references=actual.references+tuple(x.span for pair in matches for x in pair[:2]))
    if trace:projected.append(replace(f,arguments=tuple(args),contexts=tuple(sorted(contexts)),derivations=f.derivations+tuple(dict.fromkeys(trace))))
   return frames+projected
  def _remember_question(self,question,matches):
   q=super()._remember_question(question,matches)
   if question.predicate=='@name':
    names=[a for a in matches[0][0].arguments if a.role=='name']
    if len(names)==1:q=replace(q,arguments=tuple(a for a in q.arguments if a.role not in {'nsubj','name'})+(replace(names[0],role='nsubj'),))
   return q
  def answer(self,question,text,**kwargs):
   if not isinstance(question,str) or not isinstance(text,str):raise ValueError('Domanda e testo devono essere stringhe.')
   if len(question)>512 or len(text)>16384:raise ValueError('Domanda o passaggio oltre il limite di lettura.')
   if re.search(r'\b(?:riga|righe|verso|versi)\s+\d',question,re.I):
    self.last=None;self.last_result=None;self.reference_pending=None
    self.reference_previous=None;self.lexical_pending=None;self.pending=None
    return dict(reader='NAMING045',value=None,reason='SOURCE_LOCATOR_REQUIRES_REFERENCE042',status='CLARIFY',
      answer='Questa richiesta richiede la verifica della posizione nella fonte.',llm_calls=0,factual_answer_authorized=False,proofs=[])
   previous_key=(self.source_hash,self.scope,getattr(self,'selection',None))
   current_key=(pc.digest(text),kwargs.get('source','provided-passage'),kwargs.get('scope'))
   if self.source_hash is not None and previous_key!=current_key:
    q=self._parse_question(question)
    if q is not None and q.target[0]!='nsubj':
     ts=reader.parse(question)
     explicit_subject=any(t.rel.startswith('nsubj') and t.pos!='PRON' for sent in ts for t in sent)
     if not explicit_subject:
      self.last=None;self.last_result=None;self.reference_pending=None;self.reference_previous=None
      self.lexical_pending=None;self.pending=None;self.source_hash=None;self.frames=[]
      return dict(reader='NAMING045',value=None,reason='SOURCE_CHANGED_RESTATE_SUBJECT',status='CLARIFY',
        answer='Il testo o la selezione è cambiato. Indica il soggetto della domanda.',context_used=False,llm_calls=0,factual_answer_authorized=False,proofs=[])
   self.current_question=question
   r=super().answer(question,text,**kwargs);r['reader']='NAMING045';return r
 return NamingConversation

class _CurrentParser:
 def parse(self,text):
  with _pc.LOCK:return _pc.solver().parse(text)

NamedIdentityConversation=build_naming_class(_Base,_pc,_CurrentParser())
