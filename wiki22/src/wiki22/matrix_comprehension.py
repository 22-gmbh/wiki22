"""QA033: preserve asserted matrix events with licensed adjuncts.

A purpose does not assert its realization. A postposed gerund can describe an
asserted past event without making the matrix conditional. Embedded events are
never promoted here; existing scopes and source spans remain attached.
"""
from dataclasses import replace
from . import passage_comprehension as pc
from .semantic_comprehension import SemanticConversation, event

def license_matrix(frame,ts):
    if 'subordinate_scope' not in frame.scope:return frame
    root=next((t for t in ts if t.head==0),None)
    if root is None or root.pos!='VERB' or root.lemma!=frame.predicate:return frame
    if sum(t.pos=='VERB' and t.lemma==root.lemma for t in ts)!=1:return frame
    cs=pc.children(ts,root.id)
    # Do not erase an unresolved reference to the cause in a prior sentence.
    if any(t.lemma in {'perciò','pertanto','quindi'} for t in cs):return frame
    adjuncts=[t for t in cs if t.rel=='advcl']
    if not adjuncts:return frame
    licensed=[]
    for child in adjuncts:
        marks=[t.lemma for t in pc.children(ts,child.id) if t.rel=='mark']
        form=pc.feats(child).get('VerbForm')
        if marks==['per'] and form=='Inf':
            licensed.append('purpose')
        elif not marks and form=='Ger' and child.lo>root.hi and frame.tense=='past':
            licensed.append('postposed_past_gerund')
        elif marks==['perché']:
            # Already represented as a cause by the predecessor; preserve it.
            continue
        else:return frame
    if not licensed:return frame
    # Only remove the blanket subordinate guard; negative, reported, quoted,
    # conditional, retracted, hypothetical and other scopes survive unchanged.
    return replace(frame,scope=tuple(s for s in frame.scope if s!='subordinate_scope'),
                   derivations=frame.derivations+tuple('matrix_assertion:'+k for k in licensed))

class MatrixConversation(SemanticConversation):
    def _read_frames(self,text):
        frames,error=super()._read_frames(text)
        if error:return frames,error
        with pc.LOCK:sentences=pc.solver().parse(text)
        by_span={(min(t.lo for t in ts),max(t.hi for t in ts)):ts for ts in sentences if ts}
        frames=[license_matrix(f,by_span[f.span]) if f.span in by_span else f for f in frames]
        self.events=[e for f in frames if (e:=event(f)) is not None]
        return frames,error
    def _candidate_frames(self,question):
        frames=super()._candidate_frames(question)
        if question.wh not in {'quando','anno'}:return frames
        guarded=[]
        for f in frames:
            malformed=False
            for a in pc.target_arguments(question,f,self.text):
                if a.kind=='NUM' and any(k.isdecimal() for k in a.key):
                    allowed=pc.MONTHS|{'di','a','e','-','/','.'}
                    if any(not k.isdecimal() and k not in allowed for k in a.key):malformed=True
            if malformed:f=replace(f,scope=f.scope+('temporal_attachment_unresolved',))
            guarded.append(f)
        return guarded
    def answer(self,question,text,*,source='provided-passage',scope=None):
        result=super().answer(question,text,source=source,scope=scope)
        result['reader']='QA033'
        return result

def comprehend(question,text):
    return MatrixConversation().answer(question,text)
