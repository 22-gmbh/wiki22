"""QA035: complete nominal copular questions with retained modifiers."""
from dataclasses import replace
from . import passage_comprehension as pc
from .clause_comprehension import ClauseConversation

def nominal_question(text):
    if len(text)>512:return None
    with pc.LOCK:sentences=pc.solver().parse(text)
    if len(sentences)!=1:return None
    ts=sentences[0];root=next(t for t in ts if t.head==0);cs=pc.children(ts,root.id)
    if not any(t.rel=='cop' for t in cs):return None
    if any(t.lemma in pc.MODAL|pc.NEG or t.rel.split(':')[0] in pc.CLAUSE for t in ts):return None
    elided=(root.lemma=='cos' and any(t.lemma=='che' and 'PronType=Int' in t.feats for t in cs)
            and any(t.form in {"'",'’'} and t.rel=='punct' for t in cs))
    if root.lemma in {'cosa','quale'} or elided:
        anchors=[t for t in cs if t.rel=='nsubj']
        if len(anchors)!=1:return None
        for t in cs:
            if t.id==anchors[0].id or t.rel in {'cop','punct'} or t.rel.startswith('aux'):continue
            if t.rel=='det' and t.lemma=='che' and 'PronType=Int' in t.feats:continue
            return None
        anchor=pc.argument(text,ts,anchors[0])
        return pc.Frame('@copula',pc.tense(ts,root),(anchor,),(0,len(text)),(),
                        wh='quale' if root.lemma=='quale' else 'cosa',target=('predicate',()),
                        derivations=('nominal_question:interrogative_root',))
    if root.pos not in {'NOUN','PROPN','ADJ'}:return None
    slots=[]
    for t in cs:
        if t.rel!='nsubj':continue
        if t.lemma in {'quale','cosa'}:slots.append(t)
        elif t.lemma=='cos' and any(x.lemma=='che' and 'PronType=Int' in x.feats for x in pc.children(ts,t.id)):
            # Explicit written elision in "che cos'è", not arbitrary spelling repair.
            if any(x.form in {"'",'’'} and x.rel=='punct' for x in pc.children(ts,t.id)):slots.append(t)
    if len(slots)!=1:return None
    slot=slots[0]
    nominal={'nmod','amod','det','case','compound','flat','flat:name','nummod'}
    if any(t.id!=slot.id and t.rel not in nominal|{'punct','cop'} and not t.rel.startswith('aux') for t in cs):return None
    remove={t.id for child in cs if child.id==slot.id or child.rel in {'cop','punct'} or child.rel.startswith('aux') for t in pc.subtree(ts,child.id)}
    kept=[t for t in ts if t.id not in remove]
    anchor=replace(pc.argument(text,kept,root),role='nsubj')
    if not anchor.key:return None
    # Both copular orientations already have source-bound matching in the base
    # reader. The complete nominal anchor, including modifiers, must match.
    return pc.Frame('@copula',pc.tense(ts,root),(anchor,),(0,len(text)),(),
                    wh='quale' if slot.lemma=='quale' else 'cosa',target=('predicate',()),
                    derivations=('nominal_question:complete_anchor',))

class NominalQuestionConversation(ClauseConversation):
    def _parse_question(self,question):
        previous=super()._parse_question(question)
        return previous if previous is not None else nominal_question(question)
    def _candidate_frames(self,question):
        frames=super()._candidate_frames(question)
        if question.wh!='cosa' or not question.derivations or len(question.arguments)!=1:return frames
        anchor=question.arguments[0]
        with pc.LOCK:sentences=pc.solver().parse(self.text)
        guarded=[]
        for f in frames:
            if f.predicate=='@copula' and not any(pc.compatible(anchor,a) for a in f.arguments):
                predicates=[a for a in f.arguments if a.role=='predicate' and pc.compatible(anchor,replace(a,role='nsubj'))]
                if len(predicates)==1 and predicates[0].kind not in {'PROPN','NUM'}:
                    pred=predicates[0];definite=False
                    for ts in sentences:
                        root=next(t for t in ts if t.head==0)
                        if pred.span[0]<=root.lo<root.hi<=pred.span[1]:
                            definite=any(t.rel=='det' and pc.feats(t).get('Definite')=='Def' for t in pc.children(ts,root.id))
                    if not definite:f=replace(f,scope=f.scope+('copular_class_not_identity',))
            guarded.append(f)
        return guarded
    def answer(self,question,text,*,source='provided-passage',scope=None):
        result=super().answer(question,text,source=source,scope=scope)
        result['reader']='QA035'
        return result

def comprehend(question,text):return NominalQuestionConversation().answer(question,text)
