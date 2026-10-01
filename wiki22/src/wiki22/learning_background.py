"""Bounded, source-revalidated learning from the user's selected reading."""
import json
import queue
import threading
from datetime import datetime,timezone
from .workspace_state import WorkspaceState
from .knowledge.library_registry import LibraryRegistry
from .knowledge.scope import resolve_scope,build_scope_provider
from .study import StudyEngine
from .native22_linguistic_guarded.session import NativeSession
from .offline import OfflineGuard

def learn_topic(root,topic,ids):
    state=WorkspaceState(root);prefs=state.preferences()
    if not prefs['automatic_learning']:return dict(status='PAUSED',topic=topic)
    scope=resolve_scope(LibraryRegistry(root),mode='SINGLE' if len(ids)==1 else 'CUSTOM',requested_ids=ids)
    provider=build_scope_provider(root,scope);session=None
    try:
        engine=StudyEngine(provider);choices=engine.find(topic)
        if len(choices)!=1:return dict(status='AMBIGUOUS_OR_MISSING',topic=topic)
        book=engine.open(choices[0]['article_id'])
        if book['status']!='READY':return dict(status='NO_VERIFIED_READING',topic=topic)
        eids=list(dict.fromkeys(s['evidence_id'] for p in book['paragraphs'] for s in p['spans']))[:prefs['learning_budget']]
        if engine.open(book['article_id'])!=book:raise ValueError('Lettura cambiata prima dell’apprendimento.')
        session=NativeSession(state.path.parent/'native22/memory.sqlite3')
        before=session.engine.metriche_stato();results=[]
        for eid in eids:
            if not state.preferences()['automatic_learning']:break
            # NativeSession binds each observation to a fresh canonical source
            # and rejects fixtures, oversized material and duplicate observations.
            results.append(session.observe(provider,eid))
        after=session.engine.metriche_stato()
        return dict(status='COMPLETED',topic=book['title'],scope=list(scope.library_ids),at=datetime.now(timezone.utc).isoformat(),
                    attempted=len(results),new_observations=sum(r['status']=='OBSERVED' for r in results),
                    receipts=results,before=before,after=after,
                    growth={k:after[k]-before[k] for k in before},source_revision=book['revision_id'],model_calls=0,
                    promotes_user_assertions=False,scope_note='Canonical source observations, including unclassified lexical hypotheses; not independent factual validation')
    finally:
        if session:session.close()
        if hasattr(provider,'close'):provider.close()

class LearningCoordinator:
    def __init__(self,root):
        self.root=root;self.queue=queue.Queue(maxsize=8);self.closed=threading.Event();self.last=None
        self.worker=threading.Thread(target=self.run,daemon=True);self.worker.start()
    def submit(self,topic,ids):
        if self.closed.is_set() or not WorkspaceState(self.root).preferences()['automatic_learning']:return False
        try:self.queue.put_nowait((topic,list(ids)));return True
        except queue.Full:return False
    def run(self):
        while not self.closed.is_set():
            try:item=self.queue.get(timeout=.2)
            except queue.Empty:continue
            try:
                with OfflineGuard():receipt=learn_topic(self.root,*item)
            except Exception as exc:receipt=dict(status='ERROR',topic=item[0],error=str(exc),at=datetime.now(timezone.utc).isoformat())
            self.last=receipt
            state=WorkspaceState(self.root)
            try:
                with state.connect() as db:
                    db.execute('CREATE TABLE IF NOT EXISTS learning_events (id INTEGER PRIMARY KEY,body TEXT NOT NULL)')
                    db.execute('INSERT INTO learning_events(body) VALUES (?)',(json.dumps(receipt,ensure_ascii=False),))
            except Exception as exc:
                self.last=dict(status='ERROR',topic=item[0],error='Registro degli apprendimenti non aggiornato: '+str(exc))
            finally:self.queue.task_done()
    def close(self):self.closed.set()

def recent_learning(root):
    state=WorkspaceState(root)
    with state.connect() as db:
        if not db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='learning_events'").fetchone():return []
        return [json.loads(row[0]) for row in db.execute('SELECT body FROM learning_events ORDER BY id DESC LIMIT 20')]
