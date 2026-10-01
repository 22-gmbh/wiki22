"""Derived title lookup: accent-insensitive prefixes and explicit typo suggestions.

Never changes 22CK, titles, IDs or factual evidence. The cache is disposable and
bound to source file stamps; it is not a knowledge source.
"""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unicodedata


def fold(text):
    text=unicodedata.normalize('NFKD',text.casefold())
    text=''.join(c for c in text if not unicodedata.combining(c))
    text=text.translate(str.maketrans({'’':"'",'‘':"'",'‐':'-','‑':'-','–':'-','—':'-'}))
    return ' '.join(text.split())


def edits1(word):
    """One insertion, deletion, substitution or adjacent transposition."""
    alphabet='abcdefghijklmnopqrstuvwxyz0123456789 '+''.join(sorted(set(word)))
    splits=[(word[:i],word[i:]) for i in range(len(word)+1)]
    result={a+b[1:] for a,b in splits if b}
    result.update(a+b[1]+b[0]+b[2:] for a,b in splits if len(b)>1)
    result.update(a+c+b[1:] for a,b in splits if b for c in alphabet)
    result.update(a+c+b for a,b in splits for c in alphabet)
    return sorted(x for x in result if len(x)>=2 and x!=word and x==x.strip())


def source_rows(provider):
    if getattr(provider,'document_db',None) is not None:
        yield from provider.document_db.execute('SELECT aid,title FROM documents')
    elif hasattr(provider,'readers'):
        from .knowledge.compact22.runtime_v3 import readstring,readint
        for reader in provider.readers:
            if hasattr(reader,'store'):
                for i in range(reader.store.tables['articles']['count']):
                    raw=reader.store.record('articles',i)
                    aid,pos=readstring(raw);title,_=readint(raw,pos)
                    yield aid,reader._string(title)
            else:
                for a in reader.iter_articles():yield a['article_id'],a['title']
    elif hasattr(provider,'_articles'):
        for aid,a in provider._articles.items():yield aid,a['title']
    else:raise ValueError('Indice dei titoli non disponibile.')


class TitleIndex:
    def __init__(self,provider,directory):
        self.provider=provider
        ensure=getattr(provider,'_ensure_unchanged',None)
        if ensure:ensure()
        stamps=getattr(provider,'_file_stamps',None)
        if stamps:
            identity=[(str(p),list(s)) for p,s in sorted(stamps.items())]
        else:
            p=Path(provider.real_pack_path);s=p.stat()
            identity=[str(p),s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
        key=hashlib.sha256(json.dumps(['TITLE064-v1',identity],sort_keys=True).encode()).hexdigest()
        directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
        self.path=directory/(key+'.sqlite3')
        if not self.path.exists():
            fd,name=tempfile.mkstemp(prefix=key+'-',suffix='.tmp',dir=directory);os.close(fd)
            try:
                with closing(sqlite3.connect(name)) as db, db:
                    db.execute('PRAGMA journal_mode=OFF');db.execute('PRAGMA synchronous=OFF')
                    db.execute('PRAGMA cache_size=-16384')
                    db.execute('CREATE TABLE titles (key TEXT NOT NULL, aid TEXT NOT NULL, title TEXT NOT NULL, PRIMARY KEY(key,aid)) WITHOUT ROWID')
                    db.executemany('INSERT INTO titles VALUES (?,?,?)',((fold(t),a,t) for a,t in source_rows(provider)))
                if ensure:ensure()
                os.replace(name,self.path)
            finally:
                if os.path.exists(name):os.unlink(name)
        self.db=sqlite3.connect(self.path.as_uri()+'?mode=ro',uri=True,check_same_thread=False)
        self.db.execute('PRAGMA query_only=ON')

    def close(self):self.db.close()

    def page(self,query,after=('', ''),limit=31):
        ensure=getattr(self.provider,'_ensure_unchanged',None)
        if ensure:ensure()
        return self._page(query,after,limit)

    def _page(self,query,after=('', ''),limit=31):
        key=fold(query)
        rows=self.db.execute('SELECT key,aid,title FROM titles WHERE key>=? AND key<? AND (key,aid)>(?,?) ORDER BY key,aid LIMIT ?',
                             (key,key+'\U0010ffff',*after,limit)).fetchall()
        return [dict(key=k,article_id=a,title=t) for k,a,t in rows]

    def similar(self,query,limit=8):
        key=fold(query)
        if not 3<=len(key)<=40:return []
        ensure=getattr(self.provider,'_ensure_unchanged',None)
        if ensure:ensure()
        found={}
        # Each indexed range is bounded: never scans Wikipedia on each keystroke.
        for variant in edits1(key):
            for row in self._page(variant,limit=2):
                aid=row['article_id']
                rank=(0 if row['key']==variant else 1,len(row['key']),row['key'],aid)
                if aid not in found or rank<found[aid][0]:found[aid]=(rank,row)
        return [dict(row,match='similar') for _,row in sorted(found.values(),key=lambda x:x[0])[:limit]]
