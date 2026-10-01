"""PROPERTY047: retain the semantic predicate of copular questions."""
import re
from dataclasses import replace
from . import passage_comprehension as pc
from .nominal_description import NominalDescriptionConversation

class CopularConversation(NominalDescriptionConversation):
 def _parse_question(self,question):
  previous=super()._parse_question(question)
  if len(question)>512:return previous
  expanded=re.sub(r"^che cos[’']è\b",'Che cosa è',question.strip(),flags=re.I)
  with pc.LOCK:ss=pc.solver().parse(expanded)
  if len(ss)!=1:return previous
  ts=ss[0];root=next(t for t in ts if t.head==0);cs=pc.children(ts,root.id)
  cop=[t for t in cs if t.rel=='cop' and t.lemma=='essere']
  if not cop or previous is not None and previous.predicate=='@name':return previous
  # A copular question must account for all branches; do not fall back to the
  # predecessor representation that could silently omit its predicate.
  whs=[t for t in ts if t.lemma in {'chi','cosa','quale'} and t.pos in {'PRON','DET'}]
  if len(whs)!=1 or len(cop)!=1:return None
  wh=whs[0]
  if wh.id==root.id:
   subs=[t for t in cs if t.rel=='nsubj']
   if len(subs)!=1:return None
   anchor=subs[0]
  elif wh.head==root.id and wh.rel=='nsubj':anchor=root
  else:return None
  if anchor.pos not in {'NOUN','PROPN','ADJ'}:return None
  if any(t.rel.split(':')[0] in pc.CLAUSE or t.rel.startswith('aux') or t.lemma in pc.MODAL for t in ts):return None
  # Question property/name is separate from contextual obliques. All nominal
  # modifiers stay attached; unsupported adjuncts decline the complete request.
  nominal={'det','nmod','amod','case','compound','flat','flat:name','nummod'}
  kept={anchor.id};constraints=[];negative=False
  for t in cs:
   if t.id in {wh.id,anchor.id,cop[0].id} or t.rel=='punct':continue
   if t.lemma in pc.NEG and t.rel=='advmod':negative=True;continue
   if t.rel=='obl':
    constraints.append(pc.argument(expanded,ts,t));continue
   if t.head==wh.id and t.rel=='det' and t.lemma=='che':continue
   if anchor==root and t.rel in nominal:
    kept.update(x.id for x in pc.subtree(ts,t.id));continue
   return None
  if anchor!=root:kept.update(x.id for x in pc.subtree(ts,anchor.id))
  nominal_tokens=[t for t in ts if t.id in kept]
  if any(t.id!=anchor.id and t.rel not in nominal|{'advmod'} for t in nominal_tokens):return None
  # Degrees/adverbs cannot disappear, even when old source frames do not yet
  # support matching them. Conservative abstention is preferable to weakening.
  a=pc.argument(expanded,nominal_tokens,anchor)
  if not a.key:return None
  role='nsubj' if anchor.pos=='PROPN' or anchor.pos=='NOUN' and wh.lemma in {'cosa','quale'} else 'predicate'
  target=('predicate',()) if role=='nsubj' else ('nsubj',())
  return pc.Frame('@copula',pc.tense(ts,root),(replace(a,role=role),*constraints),(0,len(question)),('negative',) if negative else (),wh=wh.lemma,target=target,derivations=('copular_question:complete_predicate',))
 def _candidate_frames(self,question):
  frames=super()._candidate_frames(question)
  if question.predicate!='@copula':return frames
  # An identity substitution on either side of a copula manufactures the
  # tautology descriptor=descriptor or name=name. Keep the explicit relation.
  frames=[f for f in frames if not any(d.startswith('explicit_named_identity:') for d in f.derivations)]
  if question.target==('nsubj',()):
   with pc.LOCK:sentences=pc.solver().parse(self.text)
   inverse=[]
   for f in frames:
    if f.predicate!='@copula':continue
    subs=[a for a in f.arguments if a.role=='nsubj'];preds=[a for a in f.arguments if a.role=='predicate']
    if len(subs)!=1 or len(preds)!=1 or subs[0].kind!='NOUN' or preds[0].kind!='PROPN':continue
    # Only an explicitly definite nominal description supports this inversion.
    definite=any(t.rel=='det' and pc.feats(t).get('Definite')=='Def' and any(h.id==t.head and subs[0].span[0]<=h.lo<h.hi<=subs[0].span[1] for h in ts) for ts in sentences if min(t.lo for t in ts)>=f.span[0] and max(t.hi for t in ts)<=f.span[1] for t in ts)
    if definite:inverse.append(replace(f,arguments=tuple(replace(a,role='predicate' if a.role=='nsubj' else 'nsubj' if a.role=='predicate' else a.role) for a in f.arguments),derivations=f.derivations+('copular_question:definite_reverse',)))
   frames+=inverse
  return frames

 def answer(self,question,text,*,source='provided-passage',scope=None):
  if not isinstance(question,str) or not isinstance(text,str):raise ValueError('Question and source must be strings')
  if len(question)>512 or len(text)>16384:raise ValueError('Question/source budget exceeded')
  q=self._parse_question(question)
  # The older name guard only recognizes surface nsubj as an explicit subject.
  # A full copular request can place its named anchor at the root. Reset prior
  # dialogue when the source changes, rather than misclassifying it as ellipsis.
  if q and 'copular_question:complete_predicate' in q.derivations and self.source_hash is not None and (self.source_hash,self.scope,getattr(self,'selection',None))!=(pc.digest(text),source,scope):
   self.last=None;self.last_result=None;self.source_hash=None;self.frames=[]
   self.reference_pending=None;self.reference_previous=None;self.lexical_pending=None;self.pending=None
  result=super().answer(question,text,source=source,scope=scope)
  result['predecessor_reader']=result.get('reader');result['reader']='PROPERTY047'
  return result
