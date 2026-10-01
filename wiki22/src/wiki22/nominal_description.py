"""DESCRIPTION046: complete source appositions for explicit name descriptions.

Descriptive citation is not independent factual identity, person classification
or assertion of any narrated event. No aliases are learned from this reader.
"""
from copy import deepcopy
from . import passage_comprehension as pc
from .named_identity import NamedIdentityConversation

class NominalDescriptionConversation(NamedIdentityConversation):
 def __init__(self,lexicon,description_reader=None):
  super().__init__(lexicon)
  self.description_reader=description_reader
  self.description_previous=None
 def _description_parse(self,text):
  if self.description_reader is not None:return self.description_reader.parse(text)
  with pc.LOCK:return pc.solver().parse(text)
 def _description_request(self,question):
  # Parse independently of conversational ellipsis: the whole name must be
  # present. Never reuse an old subject or discard additional qualifications.
  import re
  # Orthographic expansion only; keep every content word and qualification.
  expanded=re.sub(r"^che cos[’']è\b",'Che cosa è',question.strip(),flags=re.I)
  ss=self._description_parse(expanded)
  if len(ss)!=1:return None
  ts=ss[0];root=next(t for t in ts if t.head==0);cs=pc.children(ts,root.id)
  cop=[t for t in cs if t.rel=='cop' and t.lemma=='essere']
  subjects=[t for t in cs if t.rel=='nsubj']
  if len(cop)!=1 or len(subjects)!=1 or pc.tense(ts,root)!='present':return None
  other=subjects[0]
  if root.lemma in {'chi','cosa'} and root.pos=='PRON' and other.pos=='PROPN':wh,subject=root,other
  elif root.pos=='PROPN' and other.lemma in {'chi','cosa'} and other.pos=='PRON':wh,subject=other,root
  else:return None
  allowed={cop[0].id,wh.id,subject.id}
  for token in ts:
   if token.id in allowed or token.rel=='punct':continue
   if token.head==wh.id and token.rel=='det' and token.lemma=='che':continue
   if token.head==subject.id and token.rel in {'flat','flat:name','compound'} and token.pos=='PROPN':continue
   return None
  names=sorted([subject]+[t for t in cs if t.head==subject.id and t.rel in {'flat','flat:name','compound'} and t.pos=='PROPN'],key=lambda t:t.id) if subject==root else pc.subtree(ts,subject.id)
  if any(t.pos!='PROPN' for t in names):return None
  return dict(name=tuple(t.form.casefold() for t in names),focus=wh.lemma)
 def _descriptions(self,text,request):
  sentences=self._description_parse(text);scopes,contexts=pc.discourse_contexts(sentences);found=[]
  for si,ts in enumerate(sentences):
   for head in ts:
    if head.pos!='PROPN':continue
    # Use just the proper name, not its apposition or a larger nominal owner.
    names=[head]+[t for t in pc.subtree(ts,head.id) if t.id!=head.id and t.rel in {'flat','flat:name','compound'} and t.pos=='PROPN' and t.head==head.id]
    names=sorted(names,key=lambda t:t.id)
    if tuple(t.form.casefold() for t in names)!=request['name']:continue
    if head.rel in {'flat','flat:name','compound','nmod'}:continue
    for app in pc.children(ts,head.id):
     if app.rel!='appos' or app.pos!='NOUN':continue
     branch=pc.subtree(ts,app.id)
     # Preserve unknown clause scope by declining it, never by stripping it.
     if any(t.id!=app.id and (t.rel.split(':')[0] in pc.CLAUSE or t.pos in {'VERB','AUX'}) for t in branch):continue
     branch=[t for t in branch if t.pos!='PUNCT']
     if not branch:continue
     lo,hi=min(t.lo for t in branch),max(t.hi for t in branch)
     covered={t.id for t in branch}
     if any(t.pos!='PUNCT' and lo<=t.lo<t.hi<=hi and t.id not in covered for t in ts):continue
     if lo<=max(t.hi for t in names):continue
     bounds=(min(t.lo for t in ts),max(t.hi for t in ts))
     found.append(dict(value=text[lo:hi],answer_span=[lo,hi],name_span=[min(t.lo for t in names),max(t.hi for t in names)],sentence_span=list(bounds),sentence=text[slice(*bounds)],description_head=app.lemma,description_key=pc.key(ts,app),context_spans=[list(s) for s in sorted(contexts[si])],context_sentences=[text[slice(*s)] for s in sorted(contexts[si])],discourse_scope=sorted(scopes[si]),rule='EXPLICIT_NOMINAL_APPOSITION'))
  # An explicit denial of the same nominal property makes a single affirmative
  # description insufficient. Word overlap can block, never authorize a fact.
  for item in found:
   for ts in sentences:
    root=next(t for t in ts if t.head==0);cs=pc.children(ts,root.id)
    if root.lemma!=item['description_head'] or not any(t.rel=='cop' for t in cs):continue
    if not any(t.lemma in pc.NEG for t in cs):continue
    subs=[t for t in cs if t.rel=='nsubj' and t.pos=='PROPN']
    if not any(tuple(x.form.casefold() for x in pc.subtree(ts,s.id) if x.pos=='PROPN')==request['name'] for s in subs):continue
    bounds=[min(t.lo for t in ts),max(t.hi for t in ts)]
    item['discourse_scope']=sorted(set(item['discourse_scope'])|{'conflicting_description'})
    item['context_spans'].append(bounds);item['context_sentences'].append(text[slice(*bounds)])
  return found
 @staticmethod
 def _citations(proofs):
  sentences=dict.fromkeys(s for p in proofs for s in p['context_sentences']+[p['sentence']])
  return '\n'.join('«'+s+'»' for s in sentences)
 def answer(self,question,text,*,source='provided-passage',scope=None):
  if not isinstance(question,str) or not isinstance(text,str):raise ValueError('Question and source must be strings')
  if len(question)>512 or len(text)>16384:raise ValueError('Question/source budget exceeded')
  key=(pc.digest(text),source,deepcopy(scope));previous=self.description_previous
  self.description_previous=None
  feedback=' '.join(question.casefold().strip(' .!?').split())
  if previous and previous[0]==key and feedback in {'come lo sai','dove lo dice','mostrami la frase','spiegati meglio','non ho capito'}:
   out=deepcopy(previous[1]);out.update(question=question,value=None,reason='EXPLAIN_SOURCE_DESCRIPTION',context_used=True)
   out['answer']='Ho collegato il nome alla descrizione nominale che lo accompagna nel testo. Non sto confermando l’evento narrato.\n'+self._citations(out['proofs']);self.description_previous=previous;return out
  original=super().answer(question,text,source=source,scope=scope)
  if original.get('value') is None and original['reason'] not in {'QUESTION_STRUCTURE','NO_MATCHING_RELATION','UNRESOLVED_SCOPE_OR_REFERENCE'}:return original
  request=self._description_request(question)
  if request is None:return original
  descriptions=self._descriptions(text,request)
  if not descriptions:return original
  base=dict(reader='DESCRIPTION046',question=question,source=source,source_sha256=key[0],value=None,proofs=descriptions,llm_calls=0,context_used=False,factual_answer_authorized=False,event_asserted=False,reference_identity_established=False,person_type_verified=False,task='source_nominal_description',status='READING')
  unique={' '.join(p['value'].casefold().split()) for p in descriptions}
  if len(unique)>1:
   return base|dict(reason='MULTIPLE_SOURCE_DESCRIPTIONS',answer='Il testo associa al nome più descrizioni; le mantengo distinte:\n'+'\n'.join('«'+p['value']+'» — «'+p['sentence']+'»' for p in descriptions))
  if any(set(p['discourse_scope']) & {'retracted','conflicting_description'} for p in descriptions):
   return base|dict(reason='QUALIFIED_SOURCE_DESCRIPTION',answer='La descrizione è accompagnata da una smentita o da un’indicazione incompatibile:\n'+'\n'.join('«'+s+'»' for p in descriptions for s in p['context_sentences']+[p['sentence']]))
  selected=descriptions[0];out=base|dict(reason='MATCHED_SOURCE_DESCRIPTION',value=selected['value'],answer='Nel testo, «'+text[slice(*selected['name_span'])]+'» è presentato con questa descrizione: «'+selected['value']+'».\n'+self._citations(descriptions))
  # Description readings are NOT inserted in the factual identity/event graph.
  self.last=None;self.last_result=None;self.description_previous=(key,deepcopy(out));return out
