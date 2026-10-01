"""Selective metadata access over the stable paged 22CK V3 format.

Does not alter container bytes or ranking. Read only the requested evidence
blocks, even for exceptionally long articles.
"""
from .compact22.runtime_v3 import readstring, readint


def article_metadata(reader, identifier):
    if not hasattr(reader, 'store'):
        row = reader.get_article(identifier)
        return dict(row, evidence_ids=row['evidence_ids'])
    try:
        _, raw = reader._find('article_lookup', identifier)
    except KeyError:
        _, raw = reader._find('title_lookup', identifier.casefold())
    _, pos = readstring(raw)
    ordinal, _ = readint(raw, pos)
    return reader._article_meta(ordinal)


def article_evidence(reader, identifier, limit):
    row = article_metadata(reader, identifier)
    if 'ranks' in row:
        return [reader._evidence(rank) for rank in row['ranks'][:limit]]
    return row['evidence'][:limit]


def title_page(reader, prefix='', after='', limit=30):
    cursor = tuple(after) if isinstance(after,(list,tuple)) else (after,'\uffff' if after else '')
    if not hasattr(reader, 'store'):
        rows = sorted(((a['title'].casefold(), a['article_id'], a['title'])
                       for a in reader.iter_articles()))
        return [dict(key=k, article_id=i, title=t) for k,i,t in rows
                if k.startswith(prefix.casefold()) and (k,i) > cursor][:limit]
    low, high = 0, reader.store.tables['title_lookup']['count']
    prefix = prefix.casefold()
    start = max(prefix, cursor[0])
    while low < high:
        mid = (low + high) // 2
        key, _ = readstring(reader.store.record('title_lookup', mid))
        if key < start:
            low = mid + 1
        else:
            high = mid
    result = []
    total = reader.store.tables['title_lookup']['count']
    for index in range(low, min(total, low + limit + 1)):
        raw = reader.store.record('title_lookup', index)
        key, pos = readstring(raw)
        if not key.startswith(prefix):
            break
        ordinal, _ = readint(raw, pos)
        row = reader._article_meta(ordinal)
        if (key,row['article_id']) > cursor:
            result.append(dict(key=key, article_id=row['article_id'], title=row['title']))
        if len(result)==limit:
            break
    return result
