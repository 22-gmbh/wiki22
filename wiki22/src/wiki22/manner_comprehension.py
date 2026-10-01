"""MANNER049: lexical manner evidence plus complete event-role matching."""
from pathlib import Path
from copy import deepcopy
import json,hashlib
from . import passage_comprehension as pc
from .adjectival_description import AdjectivalDescriptionConversation
# These forms can scope a proposition, necessity, approximation or frequency.
# A WordNet gloss mentioning manner is insufficient to resolve that ambiguity.
SCOPE_ADVERBS=set('teoricamente necessariamente ipoteticamente presumibilmente apparentemente probabilmente possibilmente eventualmente certamente sicuramente ovviamente fortunatamente sfortunatamente chiaramente evidentemente naturalmente generalmente solitamente abitualmente normalmente forse quasi circa solo soltanto sempre mai già ancora anche perfino persino neppure nemmeno'.split())
NOMINAL={'det','det:poss','nmod','amod','case','flat','flat:name','compound','nummod'}

class MannerLexicon:
 def __init__(self,path,sha256):
  raw=Path(path).read_bytes()
  if hashlib.sha256(raw).hexdigest()!=sha256:raise ValueError('Manner lexicon identity mismatch')
  self.entries=json.loads(raw)['entries']
 def evidence(self,lemma):
  if lemma.casefold() in SCOPE_ADVERBS:return None
  entries=self.entries.get(lemma.casefold(),[])
  return entries if entries and all(e['explicit_manner'] for e in entries) else None

def nominal(text,ts,t,orphan=None):
 branch=pc.subtree(ts,t.id)
 if t.pos not in {'NOUN','PROPN','NUM'} or any(x.id!=t.id and x.rel not in NOMINAL for x in branch):return None
 a=pc.argument(text,ts,t)
 dets=[x for x in pc.children(ts,t.id) if x.rel in {'det','det:poss'}]+([orphan] if orphan else [])
 signature=tuple(('definite',) if pc.feats(x).get('Definite')=='Def' else ('det',x.lemma,pc.feats(x).get('PronType','')) for x in dets)
 return dict(argument=a,surface=' '.join(text[slice(*a.span)].casefold().split()),determiners=signature)

def compatible(a,b):
 x,y=a['argument'],b['argument']
 if a['determiners']!=b['determiners'] or x.prep!=y.prep:return False
 if any(dict(x.features).get(f) and dict(y.features).get(f) and dict(x.features)[f]!=dict(y.features)[f] for f in ('Gender','Number')):return False
 return x.key==y.key or a['surface']==b['surface']

def voice(ts,root):
 cs=pc.children(ts,root.id)
 return 'passive' if any(t.rel=='aux:pass' for t in cs) and any(t.rel=='nsubj:pass' for t in cs) else 'active'

def event_tense(ts,root,v):
 auxiliaries=[t for t in pc.children(ts,root.id) if t.rel.startswith('aux')]
 if v=='passive' and len(auxiliaries)==1 and auxiliaries[0].lemma=='essere':
  f=pc.feats(auxiliaries[0])
  if f.get('Mood')!='Ind':return 'nonasserted'
  return {'Pres':'present','Past':'past','Imp':'imperfect','Fut':'future'}.get(f.get('Tense'))
 return pc.tense(ts,root)

def role(t,v):
 if t.rel in {'nsubj','nsubj:pass'}:return 'patient' if v=='passive' else 'agent'
 if t.rel=='obj':return 'patient'
 if t.rel=='obl:agent':return 'agent'
 return t.rel

class MannerConversation(AdjectivalDescriptionConversation):
 def __init__(self,lexicon,manner_lexicon):
  super().__init__(lexicon);self.manner_lexicon=manner_lexicon;self.manner_previous=None
 def _manner_request(self,question):
  with pc.LOCK:ss=pc.solver().parse(question)
  if len(ss)!=1:return None
  ts=ss[0];root=next(t for t in ts if t.head==0);cs=pc.children(ts,root.id)
  if root.pos!='VERB' or root.lemma in pc.MODAL|pc.REPORT:return None
  wh=[t for t in cs if t.lemma=='come' and t.rel in {'advmod','mark'}]
  if len(wh)!=1:return None
  args=[]
  for t in cs:
   if t==wh[0] or t.rel=='punct' or t.rel.startswith('aux'):continue
   if t.rel not in {'nsubj','nsubj:pass','obj','iobj','obl','obl:agent'}:return None
   a=nominal(question,ts,t)
   if a is None:return None
   args.append((t,a))
  if not any(t.rel in {'nsubj','nsubj:pass'} for t,a in args):return None
  if any(t.lemma in pc.NEG|pc.MODAL or t.rel.split(':')[0] in pc.CLAUSE for t in ts):return None
  voices=[voice(ts,root)]
  if voices==['active'] and pc.feats(root).get('VerbForm')=='Part' and any(t.lemma=='essere' and t.rel=='aux' for t in cs) and not any(t.rel=='obj' for t,a in args):voices.append('passive')
  return dict(predicate=root.lemma,variants=[dict(voice=v,tense=event_tense(ts,root,v),arguments=[(role(t,v),a) for t,a in args]) for v in voices])
 def _manner_proofs(self,request,text):
  with pc.LOCK:ss=pc.solver().parse(text)
  discourse,contexts=pc.discourse_contexts(ss);proofs=[]
  for si,ts in enumerate(ss):
   root=next(t for t in ts if t.head==0);cs=pc.children(ts,root.id)
   if root.pos!='VERB' or root.lemma!=request['predicate']:continue
   v=voice(ts,root);tense=event_tense(ts,root,v);args=[];orphan=None
   if si and len(ss[si-1])==1 and ss[si-1][0].pos=='DET' and text[ss[si-1][0].hi:min(t.lo for t in ts)].isspace():orphan=ss[si-1][0]
   for t in cs:
    if t.rel in {'nsubj','nsubj:pass','obj','iobj','obl','obl:agent'}:
     a=nominal(text,ts,t,orphan if t.rel.startswith('nsubj') else None)
     if a:args.append((role(t,v),a))
   matches=[q for q in request['variants'] if q['voice']==v and q['tense']==tense and all(any(r==s and compatible(a,b) for s,b in args) for r,a in q['arguments'])]
   if not matches:continue
   adverbs=[t for t in cs if t.rel=='advmod' and t.pos=='ADV' and self.manner_lexicon.evidence(t.lemma)]
   if not adverbs:continue
   flags=set(discourse[si]);excluded=[]
   if tense=='nonasserted' or root.lemma in pc.MODAL|pc.REPORT:flags.add('nonasserted_matrix')
   if any(t.lemma in pc.NEG|pc.MODAL for t in cs):flags.add('negative_or_modal_matrix')
   for t in cs:
    if t.rel=='advmod' and t not in adverbs:flags.add('additional_adverb_scope')
    if t.rel in {'ccomp','xcomp','parataxis','conj'}:flags.add('unsupported_matrix_clause')
    if t.rel=='advcl':
     if pc.feats(t).get('VerbForm')=='Ger' and not any(x.rel=='mark' for x in pc.children(ts,t.id)):
      branch=pc.subtree(ts,t.id);excluded.append([min(x.lo for x in branch),max(x.hi for x in branch)])
     else:flags.add('unsupported_matrix_clause')
    if t.rel in {'nsubj','nsubj:pass','obj','iobj','obl','obl:agent'} and nominal(text,ts,t) is None:
     relatives=[x for x in pc.children(ts,t.id) if x.rel=='acl:relcl']
     if t.rel=='obl' and t.pos=='PRON' and pc.feats(t).get('PronType')=='Dem' and pc.case(ts,t)==('in',) and len(relatives)==1:
      branch=pc.subtree(ts,t.id);excluded.append([min(x.lo for x in branch),max(x.hi for x in branch)])
     else:flags.add('unsupported_argument_scope')
   # Quotes in an excluded supplemental branch do not scope the matrix event.
   for t in ts:
    if t.form in {'"','«','»','“','”','?'} and not any(lo<=t.lo<t.hi<=hi for lo,hi in excluded):flags.add('quoted_or_questioned_matrix')
   for adverb in adverbs:
    branch=pc.subtree(ts,adverb.id)
    if len(branch)!=1:flags.add('modified_manner_not_understood')
   bounds=[orphan.lo if orphan else min(t.lo for t in ts),max(t.hi for t in ts)]
   for adverb in adverbs:
    proofs.append(dict(value=text[adverb.lo:adverb.hi],answer_span=[adverb.lo,adverb.hi],sentence=text[slice(*bounds)],sentence_span=bounds,context_spans=[list(x) for x in sorted(contexts[si])],context_sentences=[text[slice(*x)] for x in sorted(contexts[si])],scope=sorted(flags),predicate=root.lemma,voice=v,tense=tense,lexical_evidence=self.manner_lexicon.evidence(adverb.lemma),excluded_supplement_spans=excluded,question_voice_alternatives=[q['voice'] for q in request['variants']],detached_article_rejoined=orphan is not None,nominal_surface_fallback=any(a['argument'].key!=b['argument'].key and r==s and compatible(a,b) for q in matches for r,a in q['arguments'] for s,b in args),rule='EXPLICIT_LEXICAL_MANNER_AND_EVENT_ROLES'))
  return proofs
 def answer(self,question,text,*,source='provided-passage',scope=None):
  if not isinstance(question,str) or not isinstance(text,str):raise ValueError('Question and source must be strings')
  if len(question)>512 or len(text)>16384:raise ValueError('Question/source budget exceeded')
  key=(pc.digest(text),source,deepcopy(scope));previous=self.manner_previous;self.manner_previous=None
  feedback=' '.join(question.casefold().strip(' .!?').split())
  if previous and previous[0]==key and feedback in {'come lo sai','dove lo dice','mostrami la frase','spiegati meglio','non ho capito'}:
   r=deepcopy(previous[1]);r.update(question=question,value=None,reason='EXPLAIN_SOURCE_MANNER',context_used=True,answer='Ho collegato il modo all’azione e ai suoi partecipanti. La lettura è sostenuta da queste frasi:\n'+self._citations(previous[1]['proofs']));self.manner_previous=previous;return r
  original=super().answer(question,text,source=source,scope=scope)
  if original.get('value') is not None:return original
  request=self._manner_request(question)
  if request is None:return original
  proofs=self._manner_proofs(request,text)
  if not proofs:return original
  base=dict(reader='MANNER049',source=source,source_sha256=key[0],question=question,value=None,proofs=proofs,llm_calls=0,factual_answer_authorized=False,context_used=False,status='READING',task='source_event_manner')
  flags=set(s for p in proofs for s in p['scope'])
  if flags:result=base|dict(reason='QUALIFIED_SOURCE_MANNER',qualification_reasons=sorted(flags),answer='Il passaggio pertinente contiene qualificazioni da mantenere:\n'+self._citations(proofs))
  elif len({p['value'].casefold() for p in proofs})!=1:result=base|dict(reason='MULTIPLE_SOURCE_MANNERS',answer='Il testo presenta modi diversi; non ne scelgo uno solo:\n'+self._citations(proofs))
  else:result=base|dict(reason='MATCHED_SOURCE_MANNER',value=proofs[0]['value'],answer='Nel testo: «'+proofs[0]['value']+'».\n'+self._citations(proofs))
  self.last=None;self.last_result=None;self.manner_previous=(key,deepcopy(result));return result
