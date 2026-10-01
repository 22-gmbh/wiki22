"""Inspectable system description: metadata, installed components and live counts."""
import hashlib,json,tomllib
from pathlib import Path
from .native22_linguistic_guarded.identity import verify_implementation
from .knowledge.library_registry import LibraryRegistry
from .knowledge.scope import resolve_scope,build_scope_provider

TECHNOLOGIES=[
 ('AI22 / LANG001','native22_linguistic_guarded/language_engine.py','Analisi grammaticale, parole, significati e inferenze limitate'),
 ('22CK / KC001','knowledge/compact22/runtime_v3.py','Lettura compatta della conoscenza locale'),
 ('INGEST001','knowledge/ingest001.py','Importazione canonica di Wikipedia'),
 ('Retrieval / NPA','knowledge/propositions.py','Ricerca e compatibilità delle proposizioni'),
 ('MEM','native22_linguistic_guarded/session.py','Osservazioni persistenti e ripristino della memoria'),
 ('MEMIDX / Atlas / LOCO','knowledge/atlas.py','Navigazione degli indici e delle connessioni derivate'),
 ('Evidence Binding','reading_integrity.py','Verifica dei passaggi e della loro provenienza'),
 ('Reflection','native22_linguistic_guarded/language_engine.py','Controllo delle premesse, negazione e conflitti'),
 ('SELF001 / CAP001 / STATE001','self_inspection/service.py','Ispezione dei componenti e sonde autorizzate'),
 ('Apprendimento dalle letture','learning_background.py','Osservazioni in sottofondo, circoscritte alle fonti consultate'),
 ('Maturità','maturity.py','Prove interne di grammatica, ragionamento ed espressione'),
 ('Studio / Enciclopedia','encyclopedia.py','Lettura con fonti, ripasso e appunti'),
 ('Offline Guard','offline.py','Blocco delle connessioni di rete nei percorsi protetti'),
 ('Library Registry / Scope','knowledge/scope.py','Selezione e separazione delle librerie')]

def system_profile(root):
    root=Path(root);native=verify_implementation();code=Path(__file__).parent
    metadata_path=root/'pyproject.toml'
    metadata=tomllib.loads(metadata_path.read_text()).get('project',{}) if metadata_path.exists() else {}
    approved=json.loads((code/'self_inspection/probe_allowlist.json').read_text())['files']
    technologies=[]
    for name,rel,purpose in TECHNOLOGIES:
        path=code/rel;digest=hashlib.sha256(path.read_bytes()).hexdigest().upper() if path.is_file() else None
        status='IDENTITÀ_CONTROLLATA' if digest and approved.get('src/wiki22/'+rel)==digest else 'RILEVATA_NON_VALIDATA' if digest else 'NON_DISPONIBILE'
        technologies.append(dict(name=name,purpose=purpose,path=rel,sha256=digest,status=status,semantic_maturity_proven=False))
    registry=LibraryRegistry(root);libraries=[]
    for row in registry.list_libraries():
        if not row.get('enabled'):continue
        provider=None
        try:
            selected=resolve_scope(registry,mode='SINGLE',requested_ids=[row['id']]);provider=build_scope_provider(root,selected)
            stats=provider.stats();libraries.append(dict(name=row.get('name',row['id']),id=row['id'],articles=stats.get('articles'),evidence=stats.get('evidence'),partitions=stats.get('partitions'),status='APERTA',full_integrity_verified=stats.get('full_integrity_verified',False)))
        except Exception as exc:libraries.append(dict(id=row['id'],name=row.get('name',row['id']),status='ERRORE',error=str(exc)))
        finally:
            if provider and hasattr(provider,'close'):provider.close()
    return dict(schema='wiki22.system_profile.v1',name=metadata.get('name','Identità non disponibile'),package_version=metadata.get('version'),
                native_version=native['version'],native_status=native['status'],technologies=technologies,libraries=libraries,
                model_calls_required=native['model_calls_required'],human_iq=None,language_level=None,
                warning='Identità controllata significa corrispondenza del codice con il manifesto; non dimostra comprensione generale.')

def describe(profile):
    lines=[f"Sono {profile['name']}. Il motore linguistico installato è {profile['native_version']}.",
           'Sono un ambiente locale per consultare conoscenza, porre domande sulle fonti, studiare e conservare appunti.',
           f"Chiamate a modelli richieste dal nucleo: {profile['model_calls_required']}.",
           'Le mie capacità sono limitate alle strutture e ai controlli implementati. QI umano e livello A1–C2 non sono calibrati.','', 'CONOSCENZA DISPONIBILE']
    for library in profile['libraries']:
        if library['status']=='APERTA':lines.append(f"{library['name']}: {library['articles']} voci, {library['evidence']} evidenze (conteggi del lettore aperto).")
        else:lines.append(library['name']+': non disponibile.')
    lines+=['','TECNOLOGIE INSTALLATE']
    lines += [f"{t['name']} — {t['purpose']}. Stato: {t['status'].replace('_',' ').lower()}." for t in profile['technologies']]
    lines+=['',profile['warning'],'Per i risultati effettivi usa Valuta maturità e Verifica adesso.']
    return '\n'.join(lines)
