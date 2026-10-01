"""Experimental non-LLM dependency alignment; never a proficiency claim."""
from dataclasses import dataclass
from functools import lru_cache
import hashlib,re,sys,time,json,threading
from pathlib import Path
_lock=threading.RLock()
_instance=None
_asset_stamp=None

def assets():
 manifest=json.loads((Path(__file__).parent/'resources/parser_runtime.json').read_text())
 package=Path(__file__).resolve().parents[4]
 root=package/'runtime/linguistic/udpipe1'
 if not root.is_dir():root=Path(__file__).resolve().parents[3]/'data/linguistic/udpipe1'
 global _asset_stamp
 stamp=tuple((name,(root/name).stat().st_size,(root/name).stat().st_mtime_ns,(root/name).stat().st_ctime_ns) for name in manifest['files'])
 if stamp!=_asset_stamp:
  for name,record in manifest['files'].items():
   path=root/name
   if not path.resolve().is_relative_to(root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest()!=record['sha256']:raise ValueError('Grammar asset identity mismatch: '+name)
  _asset_stamp=stamp
 return root

def solver():
 global _instance
 with _lock:
  assets()
  if _instance is None:_instance=Solver()
  return _instance

def propose(question,documents):
 with _lock:
  return solver().solve(question,documents)

@dataclass(frozen=True)
class Token:
 id:int;form:str;lemma:str;pos:str;feats:str;head:int;rel:str;lo:int;hi:int
class Reader:
 def __init__(self):
  root=assets();vendor=root/'python'
  if str(vendor) not in sys.path:sys.path.insert(0,str(vendor))
  import ufal.udpipe as api
  if not Path(api.__file__).resolve().is_relative_to(vendor.resolve()):raise ValueError('Unpinned parser import')
  self.api=api
  self.model=api.Model.load(str(root/'italian.udpipe'))
  if self.model is None:raise ValueError('model unavailable')
 @lru_cache(maxsize=256)
 def parse(self,text):
  if len(text)>16384:raise ValueError('Parser document budget exceeded')
  t=self.model.newTokenizer('ranges');t.setText(text);s=self.api.Sentence();e=self.api.ProcessingError();out=[]
  while t.nextSentence(s,e):
   if len(s.words)>256:raise ValueError('Parser sentence token budget exceeded')
   if not self.model.tag(s,'',e) or not self.model.parse(s,'',e):raise ValueError(e.message)
   tokens=[];multi={}
   for m in s.multiwordTokens:
    for i in range(m.idFirst,m.idLast+1):multi[i]=(m.getTokenRangeStart(),m.getTokenRangeEnd())
   for w in s.words:
    if w.id<=0:continue
    lo,hi=multi.get(w.id,(w.getTokenRangeStart(),w.getTokenRangeEnd()))
    if not 0<=lo<hi<=len(text):raise ValueError('Invalid token span')
    tokens.append(Token(w.id,w.form,w.lemma.casefold(),w.upostag,w.feats,w.head,w.deprel,lo,hi))
   out.append(tuple(tokens))
  if e.occurred():raise ValueError(e.message)
  return tuple(out)
BLOCK=re.compile(r'\b(?:non|mai|nessun[oa]?|nessun[oi]|nulla|niente|se|forse|probabilmente|presumibilmente|secondo|ipoteticamente|ipotesi|errat[oaie]|fals[oaie]|sbagliat[oaie]|inesatt[oaie]|salvo|tranne|eccetto|soltanto|solo|quasi|circa|ogni|tutt[ioae]|alcun[ioae]|qualche|sempre|ancora|già|prima|dopo|più|meno|anche|invece|sment\w*|rettific\w*|correzion\w*|negazion\w*)\b|[«»“”\"?!;]',re.I)
BADVERBS={'potere','dovere','volere','sembrare','parere','credere','ritenere','dire','affermare','sostenere','negare','immaginare','ipotizzare','raccontare','dichiarare','riferire','supporre','pensare'}
def children(ts,i):return [t for t in ts if t.head==i]
def subtree(ts,i):
 result={i};todo=[i]
 while todo:
  h=todo.pop()
  for t in children(ts,h):
   if t.id in result:raise ValueError('cyclic parse')
   result.add(t.id);todo.append(t.id)
 return [t for t in ts if t.id in result]
def prep(ts,t):return tuple(x.lemma for x in children(ts,t.id) if x.rel=='case')
def key(ts,t):
 # Keep all lexical modifiers and nested relation labels; ignore articles only.
 return (t.lemma,t.pos,tuple(sorted((x.rel,key(ts,x)) for x in children(ts,t.id) if x.pos!='PUNCT')))
def tense(ts,root):
 verbal=[root]+[t for t in children(ts,root.id) if t.rel.startswith('aux') or t.rel=='cop']
 if any('Mood=Cnd' in t.feats or 'Mood=Sub' in t.feats or t.lemma in BADVERBS for t in verbal):return None
 if any('Tense=Fut' in t.feats for t in verbal):return 'future'
 if any('Tense=Imp' in t.feats for t in verbal):return 'imperfect'
 if any('Tense=Past' in t.feats for t in verbal):return 'past'
 if any('Tense=Fut' in t.feats for t in verbal):return 'future'
 if any('Tense=Pres' in t.feats for t in verbal):return 'present'
 return None
class Solver(Reader):
 def question(self,q):
  if len(q)>512 or BLOCK.search(q.rstrip('?. ')):return None
  ss=self.parse(q)
  if len(ss)!=1:return None
  ts=ss[0];root=next(t for t in ts if t.head==0)
  if root.pos not in {'VERB','NOUN','ADJ'} or root.lemma in BADVERBS:return None
  wh=[t for t in ts if t.lemma in {'chi','cosa','dove','quando'} or(t.pos=='NOUN' and any(x.lemma=='quale' for x in children(ts,t.id)))]
  if len(wh)!=1:return None
  w=wh[0]
  if w.head!=root.id:return None
  whids={t.id for t in subtree(ts,w.id)}
  if any(t.pos in {'VERB','AUX'} and t.id!=root.id and not t.rel.startswith('aux') for t in ts):return None
  rest=[t for t in children(ts,root.id) if t.id!=w.id and t.pos!='PUNCT' and not t.rel.startswith('aux')]
  if not rest:return None
  if any(t.pos=='PRON' for t in ts if t.id not in whids):return None
  return ts,root,w,rest
 def solve(self,q,docs):
  qq=self.question(q)
  if qq is None:return {'status':'unknown','reason':'unsupported_question'}
  qt,qr,wh,anchors=qq;matches=[];counts={'sentences':0,'eligible':0}
  if len(docs)>40 or sum(len(d['testo']) for d in docs)>262144:return {'status':'unknown','reason':'budget'}
  seen={}
  for doc in docs:
   text=doc['testo'];sid=doc['SOURCE_REF'];sha=hashlib.sha256(text.encode()).hexdigest()
   if sid in seen and seen[sid]!=sha:raise ValueError('source collision')
   if sid in seen:continue
   seen[sid]=sha
   if re.search(r'[«»“”\"]|\b(?:errat\w*|fals\w*|sbagliat\w*|inesatt\w*|sment\w*|rettific\w*|correzion\w*)\b',text,re.I):return {'status':'unknown','reason':'unresolved_context'}
   sentences=self.parse(text)
   if len(sentences)>128:return {'status':'unknown','reason':'budget'}
   # Reports and modality anywhere may scope another sentence.
   if any(t.lemma in BADVERBS and any(x.lemma==qr.lemma for x in ts) for ts in sentences for t in ts):return {'status':'unknown','reason':'modal_or_reported_context'}
   for ts in sentences:
    rr=next(t for t in ts if t.head==0);sslo=min(t.lo for t in ts);sshi=max(t.hi for t in ts)
    if BLOCK.search(text[sslo:sshi]) and (rr.pos!='VERB' or not any(t.rel.startswith('nsubj') and t.pos in {'NOUN','PROPN'} for t in ts)):
     return {'status':'unknown','reason':'unresolved_discourse_scope'}
   for ts in sentences:
    counts['sentences']+=1
    r=next(t for t in ts if t.head==0)
    if r.lemma!=qr.lemma or r.pos!=qr.pos or tense(ts,r)!=tense(qt,qr) or tense(ts,r) is None:continue
    slo=min(t.lo for t in ts);shi=max(t.hi for t in ts)
    if BLOCK.search(text[slo:shi]):return {'status':'unknown','reason':'relevant_scope_unresolved'}
    if any(t.pos=='PRON' and t.head==r.id for t in ts):continue
    if any(t.rel=='conj' and t.head==r.id for t in ts):continue
    if any('aux:pass'==t.rel for t in ts)!=any('aux:pass'==t.rel for t in qt):continue
    children_s=children(ts,r.id);bound=set()
    if any(t.rel=='advmod' for t in children_s):continue
    for a in anchors:
     found=[t for t in children_s if t.rel==a.rel and key(ts,t)==key(qt,a)]
     if len(found)!=1:break
     bound.add(found[0].id)
    else:
     counts['eligible']+=1
     candidates=[]
     for t in children_s:
      if t.id in bound or t.pos=='PUNCT' or t.rel.startswith('aux'):continue
      if wh.lemma in {'chi','cosa'}:
       if t.rel!=wh.rel or prep(ts,t)!=prep(qt,wh) or t.pos not in {'PROPN','NOUN'}:continue
      elif wh.lemma in {'quando','anno'}:
       if t.rel not in {'obl','nummod'} or not re.fullmatch(r'\d{3,4}',t.form) or prep(ts,t) not in {('in',),('di',)}:continue
      elif wh.lemma=='dove':
       if any(x.rel=='advmod' for x in children_s):continue
       if t.rel!='obl' or prep(ts,t) not in {('a',),('in',)} or t.pos!='PROPN':continue
      if wh.lemma not in {'chi','cosa','quando','anno','dove'}:
       if t.rel!=wh.rel or t.lemma!=wh.lemma or prep(ts,t)!=prep(qt,wh):continue
      # Whole nominal subtree, including internal articles and prepositions.
      answer_tokens=[x for x in subtree(ts,t.id) if not(x.head==t.id and x.rel in {'case','det'})]
      if not answer_tokens:continue
      lo=min(x.lo for x in answer_tokens);hi=max(x.hi for x in answer_tokens)
      value=text[lo:hi]
      if len(value)>180:continue
      candidates.append((value,lo,hi))
     if len(candidates)!=1:continue
     value,lo,hi=candidates[0];slo=min(t.lo for t in ts);shi=max(t.hi for t in ts)
     matches.append({'value':value,'span':[lo,hi],'sentence_span':[slo,shi],'sentence':text[slo:shi],'source':sid,'source_sha256':sha,'predicate':r.lemma,'tense':tense(ts,r),'rule':'G22_DEPENDENCY_SLOT_ALIGNMENT'})
  if not matches:return {'status':'unknown','reason':'no_structural_match',**counts}
  if len({m['value'].casefold() for m in matches})!=1:return {'status':'unknown','reason':'multiple_answers',**counts}
  return {'status':'candidate','proofs':matches,**counts}
