"""QA034: bounded composition of asserted past clauses, without an LLM.

Temporal links distinguish the matrix assertion from the subordinate event.
'Before' does not establish that its subordinate event happened. Conditional,
reported, quoted or otherwise unresolved parent readings are not projected.
"""
from dataclasses import replace
from types import FunctionType
from . import passage_comprehension as pc
from .matrix_comprehension import MatrixConversation
from .semantic_comprehension import event

TEMPORAL={('quando',):'when',('mentre',):'while',('dopo','che'):'after',('prima','che'):'before',('perché',):'because'}

def connector_tokens(ts,root):
    # UDPipe can attach the same subordinate SCONJ as mark or advmod.
    return [c for c in pc.children(ts,root.id) if c.rel=='mark' or
            c.rel=='advmod' and c.pos=='SCONJ' and c.lemma in {'quando','mentre'}]

def markers(ts,root):
    return tuple(t.lemma for c in connector_tokens(ts,root) for t in pc.nodes(ts,c))

def local_frames(text,tokens):
    # Reuse the unchanged reader with a per-call token provider. Its global
    # namespace is copied: no global parser patch, model change or reparsing.
    class ParsedClause:
        def parse(self,_text):return [tokens]
    namespace=dict(pc.read_frames.__globals__,solver=lambda:ParsedClause())
    return FunctionType(pc.read_frames.__code__,namespace)(text)[0]


def compose(text,frame,ts):
    root=next((t for t in ts if t.head==0),None)
    if root is None or root.pos!='VERB' or root.lemma!=frame.predicate:return frame,[],[]
    if frame.tense!='past' or frame.scope and set(frame.scope)!={'subordinate_scope'}:return frame,[],[]
    if sum(t.pos=='VERB' and t.lemma==root.lemma for t in ts)!=1:return frame,[],[]
    if any(t.lemma in {'perciò','pertanto','quindi'} for t in pc.children(ts,root.id)):return frame,[],[]
    adjuncts=[t for t in pc.children(ts,root.id) if t.rel=='advcl']
    if not adjuncts:return frame,[],[]
    typed=[]
    for child in adjuncts:
        marks=markers(ts,child);operator=TEMPORAL.get(marks)
        if operator is None:return frame,[],[]
        typed.append((child,operator))
    matrix=replace(frame,scope=tuple(s for s in frame.scope if s!='subordinate_scope'),
                   derivations=frame.derivations+tuple(('matrix_causal:' if op=='because' else 'matrix_temporal:')+op for _,op in typed))
    projected=[];links=[]
    for child,operator in typed:
        sub=pc.subtree(ts,child.id)
        # The connector belongs to the link, not to the child proposition.
        markids={t.id for c in connector_tokens(ts,child) for t in pc.subtree(ts,c.id)}
        sub=[replace(t,head=0,rel='root') if t.id==child.id else t for t in sub if t.id not in markids and t.pos!='PUNCT']
        clause_span=(min(t.lo for t in sub),max(t.hi for t in sub))
        link=dict(operator=operator,matrix_span=list(frame.span),clause_span=list(clause_span),projected=False)
        # No inference that a before-clause or future/modal event was realized.
        if operator=='before':link['reason']='BEFORE_DOES_NOT_ASSERT_REALIZATION'
        elif pc.tense(ts,child)!='past':link['reason']='CHILD_NOT_ASSERTED_PAST'
        else:
            candidates=local_frames(text,sub)
            # A single complete unqualified child reading only. Nested clauses,
            # pronouns without their antecedents and modals abstain. A simple
            # negative is preserved as a negative proposition, never reversed.
            valid=[f for f in candidates if f.predicate==child.lemma and set(f.scope)<={'negative'}]
            if len(candidates)==1 and len(valid)==1:
                f=valid[0]
                f=replace(f,contexts=tuple(sorted(set(f.contexts)|{frame.span})),
                          derivations=f.derivations+(('asserted_causal_child:' if operator=='because' else 'asserted_temporal_child:')+operator,))
                projected.append(f);link.update(projected=True,polarity='negative' if 'negative' in f.scope else 'positive',reason='ASSERTED_PAST_CAUSAL_CHILD' if operator=='because' else 'ASSERTED_PAST_TEMPORAL_CHILD')
            else:link['reason']='CHILD_SCOPE_OR_REFERENCE_UNRESOLVED'
        links.append(link)
    return matrix,projected,links

class ClauseConversation(MatrixConversation):
    def _read_frames(self,text):
        frames,error=super()._read_frames(text);self.clause_links=[]
        if error:return frames,error
        with pc.LOCK:sentences=pc.solver().parse(text)
        by_span={(min(t.lo for t in ts),max(t.hi for t in ts)):ts for ts in sentences if ts}
        result=[]
        for f in frames:
            matrix,children,links=compose(text,f,by_span[f.span]) if f.span in by_span else (f,[],[])
            result.append(matrix);result.extend(children);self.clause_links.extend(links)
        self.events=[e for f in result if (e:=event(f)) is not None]
        return result,error
    def answer(self,question,text,*,source='provided-passage',scope=None):
        result=super().answer(question,text,source=source,scope=scope)
        result['reader']='QA034';result['clause_relations']=list(self.clause_links)
        return result

def comprehend(question,text):return ClauseConversation().answer(question,text)
