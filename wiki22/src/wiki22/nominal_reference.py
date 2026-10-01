"""QA037: source-bound named heads with explicit supplemental descriptions.

Question constraints remain intact. Only a source proper-name head can acquire
its shorter structural key; no substring, title stripping or alias inference.
"""
from dataclasses import replace
from . import passage_comprehension as pc
from .lexical_clarification import LexicalConversation
from .nominal_question_comprehension import NominalQuestionConversation


def named_head_keys(text, argument, sentences):
    if argument.references:return ()
    keys=[]
    for ts in sentences:
        for head in ts:
            if head.pos!='PROPN' or pc.span(text,ts,head)!=argument.span or pc.key(ts,head)!=argument.key:continue
            removed=set()
            for child in pc.children(ts,head.id):
                branch=pc.subtree(ts,child.id)
                # Parentheses are supplemental only when attached directly to
                # this name. Coordinated alternatives never qualify.
                forms=[t.form for t in branch]
                parenthetic=(child.rel=='nmod' and forms.count('(')==forms.count(')')==1
                             and min(branch,key=lambda t:t.lo).form=='('
                             and max(branch,key=lambda t:t.hi).form==')')
                if child.rel!='appos' and not parenthetic:continue
                if any(t.lemma in pc.NEG|pc.MODAL|pc.REPORT or t.pos in {'VERB','AUX','CCONJ'}
                       or t.rel.split(':')[0] in pc.CLAUSE or t.rel=='conj' for t in branch):continue
                removed.update(t.id for t in branch)
            if removed:
                kept=[t for t in ts if t.id not in removed]
                short=pc.key(kept,head)
                if short and short!=argument.key:keys.append(short)
    return tuple(keys)


class ReferenceFrames(NominalQuestionConversation):
    def _read_frames(self,text):
        result=super()._read_frames(text)
        with pc.LOCK:self.reference_sentences=pc.solver().parse(text)
        self.reference_keys={a: named_head_keys(text,a,self.reference_sentences)
                             for f in result[0] for a in f.arguments}
        return result
    def _candidate_frames(self,question):
        frames=super()._candidate_frames(question);result=[]
        for f in frames:
            args=[];trace=[]
            for a in f.arguments:
                candidates=[q for q in question.arguments
                            if q.key in self.reference_keys.get(a,())
                            and pc.compatible(q,replace(a,key=q.key))]
                if len(candidates)==1:
                    trace.append('named_head_supplement:'+str(a.span[0])+':'+str(a.span[1]))
                    a=replace(a,key=candidates[0].key)
                args.append(a)
            result.append(replace(f,arguments=tuple(args),derivations=f.derivations+tuple(trace)))
        return result


class NominalReferenceConversation(LexicalConversation,ReferenceFrames):
    # Place reference projection in the lexical reader's cooperative super
    # chain so initial suggestions and confirmed readings use the same frames.
    def answer(self,*args,**kwargs):
        result=super().answer(*args,**kwargs);result['reader']='QA037';return result
