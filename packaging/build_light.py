"""Create small portable previews, reusing runtimes from verified 1.9.0 installers.

The original installers are read in place. Wikipedia and personal data are never
copied. Inputs are verified against the published full-installer SHA-256 hashes.
"""
from pathlib import Path
import argparse
import hashlib
import json
import zipfile

ROOT=Path(__file__).resolve().parents[1]
EXPECTED={'Linux':'ed68e3ff657e79c82a28f68e0cefbd78703cd2e08d94dd2479656363921dfaf1','Windows':'76c265ae872e340ba3accef00a475d3b2396a3836dc2dbed29b8659df034f2e5'}


def build(platform,source,output):
    with source.open('rb') as f:
        if hashlib.file_digest(f,'sha256').hexdigest()!=EXPECTED[platform]:raise ValueError('Installer sorgente diverso dalla versione verificata')
    prefix='Wiki22-'+platform+'/'
    top='Wiki22-1.10-anteprima-'+platform+'/'
    output.mkdir(parents=True,exist_ok=True)
    result=output/(top[:-1]+'.zip')
    records={}
    with zipfile.ZipFile(source) as old, zipfile.ZipFile(result,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as new:
        def add(name,data,mode=0o644):
            info=zipfile.ZipInfo(top+name,date_time=(2026,10,2,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=(0o100000|mode)<<16
            new.writestr(info,data);records[name]=dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
        for info in old.infolist():
            rel=info.filename.removeprefix(prefix)
            if info.is_dir() or not info.filename.startswith(prefix):continue
            if rel.startswith(('runtime/','Licenze/')) or rel in ('Avvia Wiki22.sh','Arresta Wiki22.sh','Avvia Wiki22.cmd','Arresta Wiki22.cmd'):
                mode=0o755 if rel.endswith('.sh') or '/bin/' in rel else 0o644
                add(rel,old.read(info),mode)
        for path in sorted((ROOT/'wiki22/src').rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix!='.pyc':add(path.relative_to(ROOT).as_posix(),path.read_bytes())
        for name in ('start.py','LICENSE','PRIVACY.md','THIRD_PARTY_NOTICES.md','UNINSTALL.md'):
            add(name,(ROOT/name).read_bytes())
        add('Dati-personali/data/libraries/registry.json',(ROOT/'Dati-personali/data/libraries/registry.json').read_bytes())
        add('VERSIONE.json',json.dumps(dict(version='1.10.0-preview.1',platform=platform,wikipedia_included=False,signed=False)).encode())
        add('LEGGIMI.txt',('WIKI22 1.10 — ANTEPRIMA LEGGERA\n\nEstrai tutta questa cartella in Documenti. Avvia «Avvia Wiki22.'+('sh' if platform=='Linux' else 'cmd')+'». Il runtime è incluso: non serve installare Python.\n\nScegli «Scarica biblioteche» per Wikipedia italiana (5,84 GB, circa 7,1 GB liberi durante la preparazione). Puoi mettere in pausa e riprendere. Dopo il download la lettura è offline.\n\nLa «Sonda delle fonti» esplora i file/cartelle e gli indirizzi web scelti, mostra un’anteprima e converte solo i documenti selezionati. Crea più librerie per comporre la tua biblioteca.\n\nQuesta anteprima usa una cartella personale separata: non sostituire la tua vecchia installazione. «Arresta Wiki22» chiude il servizio.\n\nWindows non ancora collaudato su hardware reale. Pacchetto non firmato: non disattivare le protezioni del sistema. Firma SignPath in attesa di valutazione.\n').encode())
        add('INTEGRITA.json',json.dumps(records,indent=2).encode())
    with result.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
    return dict(file=result.name,bytes=result.stat().st_size,sha256=sha)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--installers',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    rows=[]
    for platform,filename in [('Linux','Installa-Wiki22-Linux'),('Windows','Installa-Wiki22-Windows.exe')]:
        r=build(platform,args.installers/filename,args.output);rows.append(r);print(json.dumps(r),flush=True)
    (args.output/'Wiki22-1.10-SHA256SUMS.txt').write_text(''.join(r['sha256']+'  '+r['file']+'\n' for r in rows))
    (args.output/'Wiki22-1.10-pacchetti.json').write_text(json.dumps(rows,indent=2)+'\n')
