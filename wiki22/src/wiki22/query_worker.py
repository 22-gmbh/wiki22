"""One offline process reuses learned language; each request gets fresh scope."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import signal
import time

MAX_REQUEST_BYTES=65536
MAX_RESPONSE_BYTES=4*1024*1024

def source_identity():
    base=Path(__file__).parent
    return hashlib.sha256(b''.join(str(p.relative_to(base)).encode()+b'\0'+hashlib.sha256(p.read_bytes()).digest()
        for p in sorted(base.rglob('*')) if p.is_file() and p.suffix in {'.py','.json'})).hexdigest()

class QueryService:
    def __init__(self,workspace_root,wiki22_root):
        from .lazy_memory import LazyNativeSession
        from .ai22_adapter import AI22Adapter
        self.root=Path(wiki22_root);self.workspace=Path(workspace_root)
        self.identity=source_identity()
        self.session=LazyNativeSession(self.root/'.runtime/native22/memory.sqlite3')
        self.adapter=AI22Adapter(workspace_root=self.workspace,wiki22_root=self.root)
        self.requests=0
        self.provider=None
        self.provider_key=None
        from .study import DialogueContext
        self.dialogue=DialogueContext()

    def close(self):
        if self.provider is not None:
            self.provider.close()
            self.provider=None
        self.session.close()
        self.adapter.close()

    def warmup(self):
        if source_identity()!=self.identity:raise ValueError('Product changed before memory preparation')
        start=time.perf_counter()
        engine=self.session.engine
        count=self.session.journal.execute('SELECT count(*) FROM observations').fetchone()[0]
        if source_identity()!=self.identity:raise ValueError('Product changed during memory preparation')
        return dict(status='READY',warmup_seconds=time.perf_counter()-start,observations=count,requests=self.requests)

    def query(self,request):
        from .knowledge.library_registry import LibraryRegistry
        from .knowledge.scope import resolve_scope,build_scope_provider
        from .query_engine import QueryEngine
        from .ui import Wiki22LocalUI
        if source_identity()!=self.identity:raise ValueError('Product changed: restart the local query process')
        query=request.get('query');scope=request.get('scope')
        if not isinstance(query,str) or not query.strip() or len(query)>4096 or '\n' in query:
            raise ValueError('Invalid bounded question')
        if not isinstance(scope,dict) or set(scope)!={'mode','library_ids'}:raise ValueError('Explicit scope snapshot required')
        if not isinstance(scope['library_ids'],list) or not all(isinstance(x,str) and len(x)<=200 for x in scope['library_ids']) or len(scope['library_ids'])>32:
            raise ValueError('Invalid library selection')
        self_question=' '.join(query.casefold().strip().rstrip('?!.').split())
        if self_question in {'chi sei','che cosa sai fare','cosa sai fare','quali tecnologie usi','come funzioni','qual è il tuo qi','che livello linguistico hai'}:
            from .system_profile import system_profile,describe
            profile=system_profile(self.root)
            output=io.StringIO()
            Wiki22LocalUI._emit(output,'ANSWER',dict(status='ANSWERED',answer=describe(profile),answer_type='LOCAL_SYSTEM_DESCRIPTION',navigation=dict(topics=[])))
            Wiki22LocalUI._emit(output,'SUPPORTING EVIDENCE',[])
            Wiki22LocalUI._emit(output,'QUERY TRACE',dict(self_profile=profile,model_calls=0,knowledge_library_used=False))
            self.dialogue.topic=None;self.dialogue.choices=[];self.dialogue.intent=None
            return dict(raw=output.getvalue(),requests=self.requests,scope=list(scope['library_ids']),status='ANSWERED')
        registry=LibraryRegistry(self.root)
        selected=resolve_scope(registry,mode=scope['mode'],requested_ids=scope['library_ids'])
        # Reuse bounded compact-reader caches, never cached answers. Resolve
        # selection and paths anew; the provider checks every resource stamp.
        key = (selected.mode, tuple((lid, str(registry.resolve_pack(lid))) for lid in selected.library_ids))
        if self.provider is not None and self.provider_key != key:
            self.provider.close(); self.provider=None
        if self.provider is not None:
            self.provider._ensure_unchanged()
            provider=self.provider
        else:
            provider=build_scope_provider(self.root,selected)
            if hasattr(provider, '_ensure_unchanged'):
                self.provider=provider; self.provider_key=key
        started=time.perf_counter()
        try:
            from .language_requests import normalize_request
            from .request_meaning import trace as request_trace
            normalized=normalize_request(query)
            resolved,context_topic=self.dialogue.resolve(normalized,key,provider)
            from .study import StudyEngine, normalized as topic_normalized
            # A bare exact title is a request to introduce that subject. It must
            # not turn a failed question into an unrelated encyclopedia entry.
            if len(resolved)<=180 and not any(c in resolved for c in '?\n'):
                rows=StudyEngine(provider).find(resolved)
                if len(rows)==1 and topic_normalized(rows[0]['title'])==topic_normalized(resolved):
                    resolved='Parlami di '+rows[0]['title']
            from .workspace_state import WorkspaceState
            self.session.learning_enabled=WorkspaceState(self.root).preferences()['automatic_learning']
            result=QueryEngine(provider,self.session).answer_with_ai22(resolved,ai22_adapter=self.adapter)
            self.dialogue.remember(resolved,result,key)
            topics=[]
            if self.dialogue.topic:topics.append(self.dialogue.topic)
            for row in result.get('related_articles',[]):
                if isinstance(row,dict) and row.get('title'):topics.append(row['title'])
            for row in result.get('supporting_evidence',[]):
                if isinstance(row,dict):
                    title=row.get('article_title') or row.get('title')
                    if title:topics.append(title)
            result['navigation']=dict(topics=list(dict.fromkeys(topics))[:16])

            if normalized!=query:
                result.setdefault('trace',{})['request_normalization']=request_trace(query,normalized)
            if context_topic:
                result.setdefault('trace',{})['dialogue_context']=dict(original_question=query,
                    resolved_question=resolved,topic=context_topic,source_reread=True)
            if source_identity()!=self.identity:raise ValueError('Product changed during the query')
            self.requests+=1
            result.setdefault('trace',{})['warm_session']=dict(requests=self.requests,scope=list(selected.library_ids),native_memory_loaded=self.session.loaded,
                current_scope_reread=True,query_seconds=time.perf_counter()-started)
            output=io.StringIO()
            Wiki22LocalUI._emit(output,'ANSWER',{k:result.get(k) for k in ['status','answer','answer_type','ai22_decision','related_articles','navigation']})
            Wiki22LocalUI._emit(output,'SUPPORTING EVIDENCE',result.get('supporting_evidence',[]))
            Wiki22LocalUI._emit(output,'QUERY TRACE',result.get('trace',{}))
            return dict(raw=output.getvalue(),requests=self.requests,scope=list(selected.library_ids),status=result['status'])
        finally:
            close=getattr(provider,'close',None)
            if close and provider is not self.provider:close()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workspace-root',type=Path,required=True);parser.add_argument('--wiki22-root',type=Path,required=True);args=parser.parse_args()
    from .offline import OfflineGuard
    def shutdown(signum,frame):raise SystemExit(0)
    signal.signal(signal.SIGTERM,shutdown)
    service=None
    try:
        with OfflineGuard():
            while True:
                raw=sys.stdin.buffer.readline(MAX_REQUEST_BYTES+1)
                if not raw:break
                if len(raw)>MAX_REQUEST_BYTES or not raw.endswith(b'\n'):raise ValueError('Oversized or incomplete request')
                request=json.loads(raw)
                if not isinstance(request,dict) or not isinstance(request.get('request_id'),int):raise ValueError('Invalid request identity')
                try:
                    if service is None:service=QueryService(args.workspace_root,args.wiki22_root)
                    if request.get('operation')=='warmup':
                        if set(request)!={'request_id','operation'}:raise ValueError('Invalid warmup request')
                        payload=service.warmup()
                    elif 'operation' in request:raise ValueError('Unknown local operation')
                    else:payload=service.query(request)
                    result=dict(request_id=request['request_id'],ok=True,**payload)
                except Exception as exc:
                    result=dict(request_id=request['request_id'],ok=False,error=type(exc).__name__+': '+str(exc))
                encoded=json.dumps(result,ensure_ascii=False,separators=(',',':')).encode()+b'\n'
                if len(encoded)>MAX_RESPONSE_BYTES:
                    encoded=json.dumps(dict(request_id=request['request_id'],ok=False,error='Response exceeds bounded protocol')).encode()+b'\n'
                sys.stdout.buffer.write(encoded);sys.stdout.buffer.flush()
    finally:
        if service is not None:service.close()

if __name__=='__main__':main()
