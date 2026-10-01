"""Reversible library management and bounded place-reading proposals."""
from copy import deepcopy
import json
from .title_search import fold

def manage(service,library_id,action,name=None):
    if not isinstance(library_id,str) or action not in ('remove','restore','rename'):raise ValueError('Operazione sulla libreria non valida.')
    with service.lock:
        before=service.registry.load();data=deepcopy(before)
        row=next((r for r in data['libraries'] if r['id']==library_id),None)
        if row is None:raise ValueError('Libreria non disponibile.')
        if action=='rename':
            if not isinstance(name,str) or not 1<=len(name.strip())<=80 or any(ord(c)<32 for c in name):raise ValueError('Scegli un nome da 1 a 80 caratteri.')
            row['name']=name.strip()
        elif action=='remove':
            if not row.get('removed'):
                row['removed_enabled']=bool(row.get('enabled'));row['removed']=True;row['enabled']=False
                row['removed_default']=data.get('default_library_id')==library_id
                if row['removed_default']:data['default_library_id']=None
        else:
            if row.get('removed'):
                if service.registry.resolve_pack(library_id) is None:raise ValueError('File della libreria non disponibile: ricollega il disco prima del ripristino.')
                row['enabled']=row.pop('removed_enabled',True);row.pop('removed',None)
                if row.pop('removed_default',False) and not data.get('default_library_id'):data['default_library_id']=library_id
        prefs=service.preferences()
        if action=='remove':
            prefs['ids']=[x for x in prefs['ids'] if x!=library_id]
            if prefs['mode']=='SINGLE' and not prefs['ids']:prefs['mode']='CUSTOM'
        service.registry.save(data)
        try:
            with service.db() as db:db.execute('INSERT OR REPLACE INTO settings VALUES(1,?)',(json.dumps(prefs),))
        except Exception:
            service.registry.save(before);raise
        if library_id in service.title_indexes:service.title_indexes.pop(library_id).close()
        cached=service.providers.pop(library_id,None)
        if cached and hasattr(cached[1],'close'):cached[1].close()
        return dict(libraries=service.libraries(),preferences=prefs,action=action,name=row['name'])


def place_readings(service,library_id,article_id,*,mode='UNIFIED',ids=None):
    with service.lock:
        place=service.article(library_id,article_id,mode=mode,ids=ids)
        title=place['title'];base=title
        # Exact selected entry plus explicit title-based themes; no geolocation inference.
        queries=[('Il luogo',title)]
        for theme in ['Storia','Geografia','Cultura','Monumenti','Musei']:
            for prefix in [theme+' di ',theme+" d'",theme+" dell'"]:
                queries.append((theme,prefix+base))
        rows=[];seen=set();limited=False
        for theme,q in queries:
            result=service.search(q,mode=mode,ids=ids,limit=8);limited|=bool(result['next'])
            for row in result['rows']:
                if '(disambigua)' in row['title'].lower():continue
                if theme=='Il luogo' and fold(row['title'])!=fold(title):continue
                if theme!='Il luogo' and not (fold(row['title'])==fold(q) or fold(row['title']).startswith(fold(q)+' ')):continue
                key=(row['library_id'],row['article_id'])
                if key in seen:continue
                if len(rows)>=60:limited=True;continue
                seen.add(key);rows.append(dict(row,theme=theme))
        return dict(title=title,rows=rows,limited=limited,method='Voci cercate per titolo nelle librerie selezionate: luogo, storia, geografia, cultura, monumenti e musei. Non è un censimento geografico completo. Scegli le fonti da riunire in una ricerca enciclopedica.')
