"""LEXICON036: lexical senses suggest explicit dialogue clarification.

A shared synset never authorizes an answer. User confirmation selects a reading
of the source predicate; the unchanged source/role/scope controller still runs.
"""
from dataclasses import replace
from pathlib import Path
from collections import defaultdict
from copy import deepcopy
import hashlib,re
from . import passage_comprehension as pc
from .nominal_question_comprehension import NominalQuestionConversation

class VerbLexicon:
    def __init__(self,path,expected_sha256):
        data=Path(path).read_bytes();self.sha256=hashlib.sha256(data).hexdigest()
        if self.sha256!=expected_sha256:raise ValueError('Identità della risorsa lessicale non valida.')
        senses=defaultdict(set)
        for line in data.decode('utf-8').splitlines():
            if line.startswith('#'):continue
            fields=line.split('\t')
            if len(fields)==3 and fields[1]=='ita:lemma' and re.fullmatch(r'\d{8}-v',fields[0]):
                lemma=fields[2].casefold()
                if lemma and not any(c.isspace() for c in lemma) and '_' not in lemma:senses[lemma].add(fields[0])
        self.senses={k:frozenset(v) for k,v in senses.items()}
    def shared(self,a,b):return sorted(self.senses.get(a,frozenset())&self.senses.get(b,frozenset()))

class LexicalConversation(NominalQuestionConversation):
    def __init__(self,lexicon):
        super().__init__();self.lexicon=lexicon;self.lexical_pending=None;self._confirmed_frame=None
    def _parse_question(self,question):
        return self._confirmed_frame if self._confirmed_frame is not None else super()._parse_question(question)
    def _clarification(self,pending,question,selection_required=False):
        options=pending['options']
        lines=['Nel testo trovo queste formulazioni. A quale evento ti riferisci?']
        for i,o in enumerate(options,1):lines.append(str(i)+'. «'+o['sentence']+'»')
        lines.append('Puoi confermare con «sì» oppure precisare la domanda.' if len(options)==1 else 'Indica il numero della formulazione oppure precisa la domanda.')
        if selection_required:lines.insert(0,'Ci sono più interpretazioni: «sì» non ne seleziona una.')
        return dict(source=pending['key'][1],source_sha256=pending['key'][0],question=question,reader='LEXICON036',status='CLARIFY',reason='LEXICAL_MEANING_CLARIFICATION',value=None,answer='\n'.join(lines),proofs=[],interpretation_options=deepcopy(options),lexicon_sha256=self.lexicon.sha256,llm_calls=0,statistical_grammar_required=True,factual_answer_authorized=False,context_used=question!=pending['question'])
    def answer(self,question,text,*,source='provided-passage',scope=None):
        if not isinstance(question,str) or not isinstance(text,str):raise ValueError('Domanda e testo devono essere stringhe.')
        if len(question)>512 or len(text)>16384:raise ValueError('Domanda o passaggio oltre il limite di lettura.')
        key=(pc.digest(text),source,deepcopy(scope));pending=self.lexical_pending;self.lexical_pending=None
        reply=' '.join(question.casefold().strip(' .!?').split());chosen=None
        if pending and pending['key']==key:
            if reply in {'sì','si','esatto','sì, intendo questo','si, intendo questo'}:
                if len(pending['options'])!=1:
                    self.lexical_pending=pending;return self._clarification(pending,question,True)
                chosen=pending['options'][0]
            elif reply.isdecimal():
                if 1<=int(reply)<=len(pending['options']):chosen=pending['options'][int(reply)-1]
                else:
                    self.lexical_pending=pending
                    result=self._clarification(pending,question)
                    result['answer']='Quel numero non identifica una delle formulazioni elencate.\n'+result['answer']
                    return result
        if chosen:
            self._confirmed_frame=replace(pending['frame'],predicate=chosen['source_predicate'],
                derivations=pending['frame'].derivations+('user_confirmed_lexical_reading',))
        try:result=super().answer(question,text,source=source,scope=scope)
        finally:self._confirmed_frame=None
        result['reader']='LEXICON036'
        if chosen:
            result['lexical_interpretation']=dict(original_question=pending['question'],question_predicate=pending['frame'].predicate,source_predicate=chosen['source_predicate'],shared_senses=chosen['shared_senses'],user_confirmed=True,world_fact_confirmed=False,lexicon_sha256=self.lexicon.sha256)
            result['context_used']=True
            if self.last_result is not None:self.last_result=deepcopy(result)
            return result
        if result.get('reason')!='NO_MATCHING_RELATION':return result
        q=super()._parse_question(question)
        if q is None or not q.arguments or q.scope:return result
        options=[];seen=set()
        for f in super()._candidate_frames(q):
            if f.predicate==q.predicate or f.predicate in seen or f.tense!=q.tense:continue
            senses=self.lexicon.shared(q.predicate,f.predicate)
            if not senses or not all(any(pc.compatible(a,b) for b in f.arguments) for a in q.arguments):continue
            if len(pc.target_arguments(q,f,text))!=1:continue
            seen.add(f.predicate)
            options.append(dict(source_predicate=f.predicate,shared_senses=senses,sentence=text[f.span[0]:f.span[1]],sentence_span=list(f.span),source_scope=list(f.scope)))
        if not options or len(options)>3:return result
        pending=dict(key=key,frame=q,question=question,options=options)
        self.lexical_pending=pending
        return self._clarification(pending,question)
