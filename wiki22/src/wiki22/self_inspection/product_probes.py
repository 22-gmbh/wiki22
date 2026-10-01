"""Reviewed behavioral probes; run only in SELF001's disposable bounded copy."""
import os
from pathlib import Path


def language_learning_and_reflection():
    from wiki22.native22_linguistic_guarded.session import make_engine
    m = make_engine()
    for i, text in enumerate(['Nereo è il fularo del porto.', 'Delio è il fularo del canale.']):
        m.osserva({'SOURCE_REF': f'probe://learn/{i}', 'testo': text})
    answer = m.rispondi('Chi è il fularo del molo?', [{'SOURCE_REF': 'probe://answer', 'testo': 'Tullio è il fularo del molo.'}])
    assert answer['STATO'] == 'VERIFICATA' and answer['VALORE'] == 'tullio'
    assert all(row['VERIFICATA'] for row in answer['RIFLESSIONE'])
    conflict = m.rispondi('Chi è il fularo del molo?', [{'SOURCE_REF': 'probe://conflict',
        'testo': 'Tullio è il fularo del molo. Tullio non è il fularo del molo.'}])
    assert conflict['STATO'] == 'CONFLITTO'
    return True


def compact_reading_and_semantic_gate():
    from wiki22.knowledge.compact22 import build_22ck_streaming_v3
    from wiki22.knowledge.compact_provider import CompactKnowledgeProvider
    from wiki22.query_engine import QueryEngine
    work = Path(os.environ['SELF001_PROBE_WORK'])
    path = work / 'probe.22ck'
    build_22ck_streaming_v3({'library_id': 'self.probe', 'library_name': 'Sonda', 'locale': 'it-IT',
        'articles': [{'article_id': 'P1', 'title': 'Altoriva', 'source_ref': 'probe://source', 'sections': [
            {'section_id': 'S1', 'title': 'Fatto', 'text': 'Altoriva è la capitale di Selvoria.'}]}]}, path)
    p = CompactKnowledgeProvider(path)
    try:
        engine = QueryEngine(p)
        assert engine.answer('Qual è la capitale di Selvoria?')['status'] == 'ANSWERED'
        assert engine.answer('Qual è la capitale di Altavia?')['status'] == 'NO_EVIDENCE'
        assert p.verify_integrity()
    finally:
        p.close()
    return True


def persistent_observation_and_replay():
    from wiki22.knowledge.corpus_import import build_pack, write_pack
    from wiki22.knowledge.real import RealKnowledgeProvider
    from wiki22.native22_linguistic_guarded.session import NativeSession
    work = Path(os.environ['SELF001_PROBE_WORK'])
    source = work / 'source.txt'
    source.write_text('Nereo è il fularo del porto. Delio è il fularo del canale.')
    pack = work / 'pack.json'
    write_pack(build_pack(source, library_id='self.memory', library_name='Sonda memoria'), pack)
    p = RealKnowledgeProvider(pack)
    eid = p.raw_candidates('fularo', limit=1)[0]['evidence_id']
    session = NativeSession(work / 'memory.sqlite3')
    try:
        assert session.observe(p, eid)['status'] == 'OBSERVED'
        metrics = session.metrics()
        assert session.user_assertion('probe://question', 'Una dichiarazione di prova.')['statute'] == 'USER_ASSERTED'
    finally:
        session.close()
    session = NativeSession(work / 'memory.sqlite3')
    try:
        assert session.metrics() == metrics
        assert session.observe(p, eid)['status'] == 'ALREADY_OBSERVED'
    finally:
        session.close()
    return True


def offline_enforcement():
    import socket
    from wiki22.offline import OfflineGuard, NetworkUnavailableError
    with OfflineGuard():
        try:
            socket.create_connection(('example.invalid', 443))
        except NetworkUnavailableError:
            return True
    raise AssertionError('Offline guard did not reject the request')


def biographic_source_roles():
    """Controlled source fixture, not a proof of general factual understanding."""
    import hashlib,json,sqlite3,struct
    from wiki22.knowledge.compact22 import build_22ck_streaming_v3,TwentyTwoCKReader
    from wiki22.knowledge.compact_provider import CompactKnowledgeProvider,CATALOG_SCHEMA
    from wiki22.knowledge.biographic_index import FIELDS,SCHEMA,PROMOTION
    from wiki22.biographic_articles import propositions,render,parse_generated
    work=Path(os.environ['SELF001_PROBE_WORK']);part=work/'bio.22ck';index=work/'bio.sqlite';catalog=work/'bio.22lib.json'
    values={'Nome':'nerilda','Attività':'cartografa','AnnoNascita':'circa 1782'}
    text='bio '+' '.join(k.casefold()+' = '+v for k,v in values.items())
    build_22ck_streaming_v3(dict(library_id='self.bio',library_name='Sonda biografica',locale='it-IT',articles=[dict(
        article_id='ITWIKI-71',title='Nerilda',source_ref='https://it.wikipedia.org/?curid=71',sections=[dict(section_id='S',title='Introduzione',text=text)])]),part)
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest().upper()
    with TwentyTwoCKReader(part) as reader:
        row=reader.get_article('ITWIKI-71')['evidence'][0];body=b''
        for key in sorted(values,key=FIELDS.index):
            pair=key.casefold()+' = '+values[key];start=row['text'].index(pair)
            body+=struct.pack('<BHH',FIELDS.index(key)+1,start,start+len(pair))
    db=sqlite3.connect(index)
    db.executescript('CREATE TABLE bios(aid INTEGER PRIMARY KEY,revision INTEGER,eid BLOB,start INTEGER,end INTEGER,fields BLOB,raw_sha BLOB,canonical_span_sha BLOB,title_sha BLOB); CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT) WITHOUT ROWID;')
    db.execute('INSERT INTO bios VALUES (?,?,?,?,?,?,?,?,?)',(71,991,bytes.fromhex(row['evidence_id'][4:]),0,len(row['text']),body,b'r'*32,hashlib.sha256(row['text'].encode()).digest(),hashlib.sha256(b'Nerilda').digest()))
    for key,value in dict(schema=SCHEMA,canonical_sha256=sha(part),source_sha256='B'*64,field_order=list(FIELDS)).items():db.execute('INSERT INTO metadata VALUES (?,?)',(key,json.dumps(value)))
    db.commit();db.close()
    catalog.write_text(json.dumps(dict(schema=CATALOG_SCHEMA,library_id='self.bio',name='Sonda',complete=False,parts=[dict(path=part.name,bytes=part.stat().st_size,sha256=sha(part),biographic_index=dict(path=index.name,bytes=index.stat().st_size,sha256=sha(index),promotion=PROMOTION))])))
    provider=CompactKnowledgeProvider(catalog)
    try:
        record=provider.biographic_record(row['evidence_id'])
        assert record['fields']['AnnoNascita']['value']=='circa 1782'
        props=propositions('Nerilda',record)
        assert any(p['group']=='Nascita' for p in props)
        for prop in props:assert parse_generated(render(prop))==prop
        replacement=work/'replaced.sqlite';replacement.write_bytes(index.read_bytes())
        try:replacement.replace(index)
        except PermissionError:
            if os.name!='nt':raise
            # Windows prevents replacing an open SQLite file. Still test the
            # provider's own change guard using a real on-disk timestamp change.
            before=index.stat()
            os.utime(index,ns=(before.st_atime_ns,before.st_mtime_ns+1_000_000_000))
        try:provider.biographic_record(row['evidence_id'])
        except ValueError:pass
        else:raise AssertionError('Replaced index was accepted')
    finally:provider.close()
    return True


def atlas_navigation_and_source_recheck():
    from wiki22.knowledge.compact22 import build_22ck_streaming_v3
    from wiki22.knowledge.compact_provider import CompactKnowledgeProvider
    from wiki22.knowledge.atlas import Atlas,browse_titles
    work=Path(os.environ['SELF001_PROBE_WORK']);path=work/'atlas.22ck'
    build_22ck_streaming_v3(dict(library_id='self.atlas',library_name='Sonda Atlante',locale='it-IT',articles=[dict(article_id='A',title='Velis',source_ref='probe://velis',sections=[dict(section_id='S',title='Introduzione',text='Velis è una città. Forse Velis è un paese.')])]),path)
    provider=CompactKnowledgeProvider(path);atlas=Atlas(provider,work/'derived.sqlite')
    try:
        metrics=atlas.search('Velis');assert metrics['evidence_examined']==1
        assert browse_titles(provider,'Vel')[0]['title']=='Velis'
        nodes=atlas.nodes('PROPOSIZIONE');assert len(nodes)==1
        source=atlas.resolve(nodes[0]['id']);assert source and 'velis' in source[0]['text']
        atlas.connections(nodes[0]['id'])
        idx=next(iter(atlas.indexes.values()));idx.nodes[nodes[0]['id']]['label']='Forged claim'
        try:atlas.resolve(nodes[0]['id'])
        except ValueError:pass
        else:raise AssertionError('Forged graph node was accepted')
    finally:atlas.close();provider.close()
    return True
