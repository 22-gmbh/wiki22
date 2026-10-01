"""DESCRIPTION048: source-complete adjectival descriptions with qualifications."""
from copy import deepcopy
from dataclasses import replace
import re
from . import passage_comprehension as pc
from .copular_comprehension import CopularConversation

class AdjectivalDescriptionConversation(CopularConversation):
 def __init__(self,lexicon):
  super().__init__(lexicon);self.adjective_previous=None
 @staticmethod
 def _determiners(ts,head):
  return tuple(('definite',) if pc.feats(t).get('Definite')=='Def' else ('det',t.lemma,pc.feats(t).get('PronType','')) for t in pc.children(ts,head.id) if t.rel=='det')
 def _adjective_request(self,question):
  expanded=re.sub(r"^com[’']è\b",'Come è',question.strip(),flags=re.I)
  with pc.LOCK:ss=pc.solver().parse(expanded)
  if len(ss)!=1:return None
  ts=ss[0];root=next(t for t in ts if t.head==0);cs=pc.children(ts,root.id)
  if root.pos not in {'PROPN','NOUN'}:return None
  wh=[t for t in cs if t.lemma=='come' and t.rel in {'advmod','mark'}]
  cop=[t for t in cs if t.lemma=='essere' and t.rel=='cop']
  if len(wh)!=1 or len(cop)!=1 or pc.tense(ts,root)=='nonasserted':return None
  nominal={'nmod','amod','det','case','flat','flat:name','compound','nummod'}
  kept={root.id};constraints=[]
  for t in cs:
   if t in wh+cop or t.rel=='punct':continue
   if t.rel=='obl':
    if any(x.id!=t.id and x.rel not in nominal for x in pc.subtree(ts,t.id)):return None
    constraints.append(pc.argument(expanded,ts,t));continue
   if t.rel not in nominal:return None
   kept.update(x.id for x in pc.subtree(ts,t.id))
  if any(t.id!=root.id and t.rel not in nominal for t in ts if t.id in kept):return None
  # Restrictions in oblique branches must also be understood as full nominals.
  if any(t.rel.split(':')[0] in pc.CLAUSE or t.pos=='VERB' or t.lemma in pc.NEG|pc.MODAL for t in ts):return None
  nominal_ts=[t for t in ts if t.id in kept]
  anchor=replace(pc.argument(expanded,nominal_ts,root),role='nsubj')
  return pc.Frame('@adjectival_description',pc.tense(ts,root),(anchor,*constraints),(0,len(question)),(),wh='come',target=('predicate',())),self._determiners(ts,root)
 def _adjective_proofs(self,request,text):
  request,determiners=request
  with pc.LOCK:ss=pc.solver().parse(text)
  frames,error=self._read_frames(text)
  if error:return []
  proofs=[]
  for ts in ss:
   root=next(t for t in ts if t.head==0);cs=pc.children(ts,root.id)
   if root.pos!='ADJ' or not any(t.rel=='cop' and t.lemma=='essere' for t in cs):continue
   subjects=[t for t in cs if t.rel=='nsubj']
   if len(subjects)!=1 or subjects[0].pos not in {'NOUN','PROPN'}:continue
   if self._determiners(ts,subjects[0])!=determiners:continue
   if any(t.rel.split(':')[0] in pc.CLAUSE for t in pc.subtree(ts,subjects[0].id)):continue
   bounds=(min(t.lo for t in ts),max(t.hi for t in ts))
   candidates=[f for f in frames if f.predicate=='@copula' and f.span==bounds and f.tense==request.tense and all(any(pc.compatible(a,b) for b in f.arguments) for a in request.arguments)]
   if not candidates:continue
   # Remove only the explicit subject and copula. Every predicate modifier,
   # degree, coordination and complement must remain in the returned text.
   excluded={x.id for t in subjects+[t for t in cs if t.rel=='cop'] for x in pc.subtree(ts,t.id)}
   branch=[t for t in ts if t.id not in excluded and t.pos!='PUNCT']
   unsupported=any(t.pos in {'VERB','AUX'} or t.rel.split(':')[0] in pc.CLAUSE or t.rel in {'nsubj','nsubj:pass','obj','iobj'} for t in branch)
   unsupported=unsupported or any(t.rel=='conj' and t.pos!='ADJ' for t in branch)
   lo,hi=min(t.lo for t in branch),max(t.hi for t in branch)
   # A negative description can surround the copula (non è stanco): preserve
   # it in the quote, never silently skip a potential denial of another match.
   unsupported=unsupported or any(t.id in excluded and t.rel!='cop' and lo<=t.lo<t.hi<=hi for t in ts)
   scopes=set(s for f in candidates for s in f.scope)
   contexts=sorted(set(span for f in candidates for span in f.contexts))
   if unsupported:scopes.add('unsupported_property_structure');lo,hi=bounds
   proofs.append(dict(value=text[lo:hi],answer_span=[lo,hi],sentence=text[slice(*bounds)],sentence_span=list(bounds),context_spans=[list(x) for x in contexts],context_sentences=[text[slice(*x)] for x in contexts],scope=sorted(scopes),rule='COMPLETE_ADJECTIVAL_SOURCE_DESCRIPTION'))
  return proofs
 def answer(self,question,text,*,source='provided-passage',scope=None):
  if not isinstance(question,str) or not isinstance(text,str):raise ValueError('Question and source must be strings')
  if len(question)>512 or len(text)>16384:raise ValueError('Question/source budget exceeded')
  key=(pc.digest(text),source,deepcopy(scope));previous=self.adjective_previous;self.adjective_previous=None
  feedback=' '.join(question.casefold().strip(' .!?').split())
  if previous and previous[0]==key and feedback in {'come lo sai','dove lo dice','mostrami la frase','spiegati meglio','non ho capito'}:
   result=deepcopy(previous[1]);result.update(question=question,value=None,reason='EXPLAIN_ADJECTIVAL_DESCRIPTION',context_used=True)
   result['answer']='La descrizione mantiene le parole e le qualificazioni del testo:\n'+self._citations(result['proofs']);self.adjective_previous=previous;return result
  request=self._adjective_request(question)
  original=super().answer(question,text,source=source,scope=scope)
  if request is None:return original
  proofs=self._adjective_proofs(request,text)
  if not proofs:return original
  base=dict(reader='DESCRIPTION048',question=question,source=source,source_sha256=key[0],value=None,proofs=proofs,llm_calls=0,context_used=False,factual_answer_authorized=False,task='adjectival_source_description',status='READING')
  # Qualified is permitted only as complete documentary reading: the qualifiers
  # are all still inside the source span. This never licenses a bare property.
  blocked=set(s for p in proofs for s in p['scope'])-{'qualified'}
  if blocked:result=base|dict(reason='QUALIFIED_ADJECTIVAL_DESCRIPTION',qualification_reasons=sorted(blocked),answer='Il testo presenta una descrizione con qualificazioni da conservare:\n'+self._citations(proofs))
  elif len({' '.join(p['value'].casefold().split()) for p in proofs})!=1:result=base|dict(reason='MULTIPLE_ADJECTIVAL_DESCRIPTIONS',answer='Il testo presenta descrizioni diverse; non ne scelgo una sola:\n'+self._citations(proofs))
  else:result=base|dict(reason='MATCHED_ADJECTIVAL_DESCRIPTION',value=proofs[0]['value'],answer='Nel passaggio la descrizione è «'+proofs[0]['value']+'».\n'+self._citations(proofs))
  self.last=None;self.last_result=None;self.adjective_previous=(key,deepcopy(result));return result
