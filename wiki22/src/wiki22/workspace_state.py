"""User-owned preferences and navigation history; never a factual memory."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
from datetime import datetime, timezone

DEFAULTS = dict(article_pages=6, verification='standard', reading_font=11, remember_searches=True, automatic_learning=True, learning_budget=3)

def validate_preferences(value):
    result = dict(DEFAULTS)
    result.update({k:v for k,v in value.items() if k in DEFAULTS})
    if type(result['article_pages']) is not int or not 1 <= result['article_pages'] <= 12:
        raise ValueError('Scegli da una a dodici pagine.')
    if result['verification'] not in ('standard','deep'):
        raise ValueError('Verifica non riconosciuta.')
    if type(result['reading_font']) is not int or result['reading_font'] not in (11,13,15):
        raise ValueError('Dimensione del testo non valida.')
    if type(result['remember_searches']) is not bool:raise ValueError('Preferenza cronologia non valida.')
    if type(result['automatic_learning']) is not bool:raise ValueError('Preferenza apprendimento non valida.')
    if type(result['learning_budget']) is not int or result['learning_budget'] not in (1,3,8):raise ValueError('Limite apprendimento non valido.')
    return result

class WorkspaceState:
    def __init__(self, root):
        self.path = Path(root)/'.runtime/workspace.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS preferences (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS searches (id INTEGER PRIMARY KEY, at TEXT NOT NULL, query TEXT NOT NULL, topic TEXT NOT NULL, scope TEXT NOT NULL, kind TEXT NOT NULL)')
    @contextmanager
    def connect(self):
        db=sqlite3.connect(self.path,timeout=5)
        db.create_function('fold',1,lambda s:s.casefold())
        try:
            with db:yield db
        finally:db.close()
    def preferences(self):
        with self.connect() as db:row=db.execute('SELECT body FROM preferences WHERE id=1').fetchone()
        return validate_preferences(json.loads(row[0]) if row else {})
    def save_preferences(self, value):
        value=validate_preferences(dict(self.preferences(),**value))
        with self.connect() as db:db.execute('INSERT OR REPLACE INTO preferences VALUES (1,?)',(json.dumps(value),))
        return value
    def record(self, query, topic, scope, kind):
        if not self.preferences()['remember_searches']:return
        if not isinstance(query,str) or not query.strip() or len(query)>4096:return
        topic=topic.strip() if isinstance(topic,str) else query.strip()
        ids=list(dict.fromkeys(scope))
        if not ids or any(not isinstance(x,str) or len(x)>200 for x in ids):return
        with self.connect() as db:
            db.execute('INSERT INTO searches(at,query,topic,scope,kind) VALUES (?,?,?,?,?)',
                       (datetime.now(timezone.utc).isoformat(),query,topic,json.dumps(ids),kind))
    def recent(self, query='', limit=150):
        with self.connect() as db:
            rows=db.execute('SELECT id,at,query,topic,scope,kind FROM searches WHERE instr(fold(query || char(10) || topic),?)>0 ORDER BY id DESC LIMIT ?',
                            (query.casefold(),min(limit,500))).fetchall()
        return [dict(id=r[0],at=r[1],query=r[2],topic=r[3],scope=json.loads(r[4]),kind=r[5]) for r in rows]


def restore_scope(selector, ids):
    """Reopen exactly the recorded libraries, never silently expand UNIFIED."""
    from .knowledge.scope import resolve_scope
    mode='SINGLE' if len(ids)==1 else 'CUSTOM'
    resolve_scope(selector.registry,mode=mode,requested_ids=ids)
    selector.current_mode=mode;selector.current_ids=list(ids);selector.refresh()
