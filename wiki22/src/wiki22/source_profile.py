"""Compact orientation from authenticated source fields, without added facts."""
def geographic_profile(provider, article_id):
    getter=getattr(provider,'geographic_record',None)
    if not callable(getter) or not getattr(provider,'supports_geographic_fields',True):return None
    book=getter(article_id)
    if book is None:return None
    from .geography import FIELDS
    lines=[];sources=[]
    for name in ('nomecompleto','continente','governo','capitale','lingua','valuta'):
        field=book['fields'].get(name)
        if not field:continue
        lines.append(FIELDS[name].capitalize()+': '+field['value'])
        lines.extend('Nota della fonte: '+n for n in field.get('notes',[]))
        sources.append(dict(article_id=article_id,article_title=book['title'],field=name,text=field['value'],
            notes=field.get('notes',[]),spans=field['spans'],evidence_id=field['spans'][0]['evidence_id'],
            source=book['original_revision_url'],revision_id=book['revision_id'],index_sha256=book['index_sha256']))
    if getter(article_id)!=book:raise ValueError('Scheda geografica cambiata durante il controllo.')
    return dict(text='\n'.join(lines),sources=sources,revision_url=book['original_revision_url']) if lines else None
