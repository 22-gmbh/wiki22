"""QA038: bounded passive participial descriptions of asserted subjects.

The grammar analysis proposes a relation; all source qualification checks still
apply. No verb synonym or passive agent is guessed from a bare preposition.
"""
from dataclasses import replace
from . import passage_comprehension as pc
from .clause_comprehension import local_frames
from .nominal_reference import NominalReferenceConversation
from .semantic_comprehension import event

QUANTIFIERS={'ogni','tutto','qualunque','qualsiasi','ciascuno','nessuno','alcuno'}
NONACTUAL={'ipotetico','immaginario','fittizio','presunto','eventuale','fantasia','finzione','sogno','invenzione','proposta'}

def participial_frames(text,ts,matrices):
    root=next(t for t in ts if t.head==0)
    # Copular descriptions can classify the entire referent as a project or
    # fiction. This successor does not resolve that ontological status.
    if root.pos!='VERB' or any(t.rel=='cop' for t in pc.children(ts,root.id)):return []
    if root.lemma in NONACTUAL:return []
    predicate='@copula' if any(t.rel=='cop' for t in pc.children(ts,root.id)) else root.lemma
    matrix=[f for f in matrices if f.predicate==predicate and not f.scope
            and f.tense in {'present','past','imperfect'}]
    if len(matrix)!=1:return []
    matrix=matrix[0];out=[]
    for child in ts:
        if child.pos!='VERB' or child.rel!='acl' or pc.feats(child).get('VerbForm')!='Part' or pc.feats(child).get('Tense')!='Past':continue
        head=next(t for t in ts if t.id==child.head)
        # A grammatical subject of this actual matrix assertion, not a name
        # buried inside a desired object, title, report or hypothetical clause.
        if head.head!=root.id or head.rel!='nsubj':continue
        ns=pc.nodes(ts,head)
        if any(t.lemma in QUANTIFIERS|NONACTUAL|pc.NEG or t.rel=='conj' for t in ns):continue
        if head.pos!='PROPN' and not (pc.feats(head).get('Number')=='Sing' and any(t.rel=='det' and pc.feats(t).get('Definite')=='Def' for t in pc.children(ts,head.id))):continue
        hf,cf=pc.feats(head),pc.feats(child)
        if any(k in hf and k in cf and hf[k]!=cf[k] for k in ('Gender','Number')):continue
        cs=pc.children(ts,child.id)
        if any(t.rel.startswith('aux') or t.rel in {'nsubj','nsubj:pass','obj','iobj','conj'} for t in cs):continue
        agents=[t for t in cs if t.rel=='obl:agent' and pc.case(ts,t)==('da',)]
        if len(agents)!=1:continue
        sub=[replace(t,head=0,rel='root') if t.id==child.id else t for t in pc.subtree(ts,child.id)]
        frames=local_frames(text,sub)
        if len(frames)!=1:continue
        f=frames[0]
        if f.predicate!=child.lemma or f.tense!='past' or set(f.scope)-{'negative'}:continue
        # Keep the complete nominal answer, including its article. Its key
        # still contains all nominal modifiers and ignores the attached clause.
        patient=replace(pc.argument(text,ts,head),role='obj',prep=(),span=pc.span(text,ts,head,outer=True))
        out.append(replace(f,arguments=f.arguments+(patient,),span=matrix.span,
                           contexts=matrix.contexts,derivations=f.derivations+('asserted_subject_passive_participle:'+str(child.lo)+':'+str(child.hi),)))
    return out

class ParticipialConversation(NominalReferenceConversation):
    def _read_frames(self,text):
        frames,error=super()._read_frames(text)
        if error:return frames,error
        with pc.LOCK:sentences=pc.solver().parse(text)
        additions=[]
        for ts in sentences:
            span=(min(t.lo for t in ts),max(t.hi for t in ts))
            additions.extend(participial_frames(text,ts,[f for f in frames if f.span==span]))
        frames=frames+additions
        self.events=[e for f in frames if (e:=event(f)) is not None]
        return frames,error
    def answer(self,*args,**kwargs):
        result=super().answer(*args,**kwargs);result['reader']='QA038';return result
