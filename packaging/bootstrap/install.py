"""Offline installer for the Wiki22 1.9 packages. No administrative rights."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
PRODUCT = 'Wiki22-Enciclopedia-1.9.0'


def default_target():
    if os.name == 'nt':
        return Path(os.environ['LOCALAPPDATA'])/'Programs/Wiki22-Enciclopedia/1.9.0'
    return Path.home()/'.local/share/wiki22-enciclopedia/1.9.0'


def previous_profile(target):
    """Reuse a validated local installation's profile; never ship personal data."""
    versions = ('1.8.1','1.8.0','1.7.1','1.7.0','1.6.0','1.5.0','1.4.0','1.3.0','1.2.1','1.2.0','1.1.2','1.1.1','1.1')
    for version in versions:
        prior = target.parent/version
        stamp = prior/'INSTALLAZIONE.json'
        if not stamp.is_file():
            continue
        try:
            if not str(json.loads(stamp.read_text())['product']).startswith('Wiki22-Enciclopedia-'):
                continue
            profile = prior/'Dati-personali'
            pointer = prior/'PROFILE.json'
            if pointer.is_file():
                profile = Path(json.loads(pointer.read_text())['path'])
            profile = profile.resolve()
            if (profile/'data/libraries/registry.json').is_file():
                return profile
        except (ValueError, KeyError, OSError):
            continue
    return None


def desktop_quote(text):
    # Desktop Exec is not a shell; these four characters need quoted escaping.
    return '"' + str(text).replace('\\', '\\\\').replace('"', '\\"').replace('`', '\\`').replace('$', '\\$').replace('%', '%%') + '"'


def shortcuts(target):
    if os.name == 'nt':
        subprocess.run([str(target/'Wiki22.exe'), '--shortcuts'], check=True, timeout=20)
        return
    menu = Path(os.environ.get('XDG_DATA_HOME', str(Path.home()/'.local/share')))/'applications'
    menu.mkdir(parents=True, exist_ok=True)
    entry = '\n'.join([
        '[Desktop Entry]', 'Type=Application', 'Version=1.0', 'Name=Wiki22 Enciclopedia',
        'Comment=La tua enciclopedia, anche senza Internet',
        'Exec=' + desktop_quote(target/'Wiki22.sh'),
        'Icon=' + str(target/'wiki22/src/wiki22/encyclopedia_web/wiki22.svg'),
        'Terminal=false', 'Categories=Education;Reference;',
        'StartupNotify=true', 'X-Wiki22-Installer=APP060', '',
    ])
    destinations = [menu/'wiki22-enciclopedia.desktop']
    chooser = shutil.which('xdg-user-dir')
    if chooser:
        d = subprocess.run([chooser, 'DESKTOP'], capture_output=True, text=True, timeout=10)
        desktop = Path(d.stdout.strip())
        if d.returncode == 0 and desktop.is_dir() and desktop != Path.home():
            destinations.append(desktop/'Wiki22 Enciclopedia.desktop')
    for dest in destinations:
        if dest.exists() and 'X-Wiki22-Installer=APP060' not in dest.read_text():
            raise ValueError('Esiste già un collegamento diverso: ' + str(dest))
        dest.write_text(entry, encoding='utf-8')
        dest.chmod(0o755)


def launch(target):
    executable = target/('Wiki22.exe' if os.name == 'nt' else 'Wiki22.sh')
    subprocess.Popen([str(executable)], cwd=target, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     **({'creationflags': 0x08000000} if os.name == 'nt' else {'start_new_session': True}))


def install(source, target, progress=lambda p, text: None, make_shortcuts=True):
    config = json.loads((HERE/'payload.json').read_text(encoding='utf-8'))
    source, target = Path(source).resolve(), Path(target).absolute()
    if target.is_symlink():
        raise ValueError('La destinazione è un collegamento: scegli una nuova cartella.')
    if target.exists():
        stamp = target/'INSTALLAZIONE.json'
        if not stamp.is_file() or json.loads(stamp.read_text())['product'] != PRODUCT:
            raise ValueError('La cartella esiste già e non verrà sovrascritta: ' + str(target))
        # Reopening the installer is idempotent; do not reset personal libraries.
        if not (target/'app_entry.py').is_file():
            raise ValueError('Installazione incompleta. Conserva la cartella e scegli una nuova destinazione.')
        if make_shortcuts:
            shortcuts(target)
        progress(100, 'Wiki22 è già installato. I tuoi dati sono conservati.')
        return {'status': 'ALREADY_INSTALLED', 'target': str(target)}
    target.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(target.parent).free < config['unpacked_bytes'] + 250_000_000:
        raise ValueError('Servono almeno 6,7 GB liberi per installare Wiki22.')
    # A single atomic directory claim serializes concurrent installations.
    lock = target.parent/(target.name+'.installazione-in-corso')
    try:
        lock.mkdir()
    except FileExistsError:
        raise ValueError('Un’installazione è già in corso. Attendi che termini.') from None
    staging = None
    try:
        progress(0, 'Verifica del pacchetto Wikipedia…')
        with source.open('rb') as stream:
            # Both SFX formats append the original ZIP as their exact final bytes.
            stream.seek(-config['zip_bytes'], 2)
            digest = hashlib.sha256()
            done = 0
            while chunk := stream.read(4 * 1024 * 1024):
                digest.update(chunk)
                done += len(chunk)
                progress(min(15, done*15/config['zip_bytes']), 'Verifica del pacchetto Wikipedia…')
        if digest.hexdigest() != config['zip_sha256']:
            raise ValueError('Il file ricevuto è incompleto o modificato. Richiedi una nuova copia.')
        staging = Path(tempfile.mkdtemp(prefix='.wiki22-install-', dir=target.parent))
        with zipfile.ZipFile(source) as archive:
            seen = set()
            expanded = 0
            for item in archive.infolist():
                parts = PurePosixPath(item.filename).parts
                if not parts or parts[0] != config['zip_root'] or '..' in parts or '\\' in item.filename or ':' in item.filename:
                    raise ValueError('Percorso non valido nel pacchetto.')
                rel = Path(*parts[1:])
                if not parts[1:] or item.is_dir():
                    continue
                if rel in seen or stat.S_ISLNK(item.external_attr >> 16):
                    raise ValueError('File duplicato o collegamento non previsto.')
                seen.add(rel)
                dest = staging/rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(item) as src, dest.open('xb') as dst:
                    while chunk := src.read(2*1024*1024):
                        dst.write(chunk)
                        expanded += len(chunk)
                        progress(15+80*expanded/config['unpacked_bytes'], 'Installazione di Wiki22 e Wikipedia…')
                dest.chmod(0o755 if item.external_attr >> 16 & 0o111 else 0o644)
        if expanded != config['unpacked_bytes']:
            raise ValueError('Dimensione del pacchetto inattesa.')
        for name in ('app_entry.py', 'window_host.py', 'gui.py'):
            shutil.copyfile(HERE/name, staging/name)
        if os.name == 'nt':
            shutil.copyfile(HERE/'Wiki22.exe', staging/'Wiki22.exe')
        else:
            script = '#!/bin/sh\nBASE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexec "$BASE/runtime/python/bin/python3.14" -X utf8 -B "$BASE/app_entry.py" "$@"\n'
            (staging/'Wiki22.sh').write_text(script)
            (staging/'Wiki22.sh').chmod(0o755)
        prior_profile = previous_profile(target)
        if prior_profile:
            (staging/'PROFILE.json').write_text(json.dumps({'path':str(prior_profile),'preserved_from_previous_installation':True},indent=2)+'\n')
        (staging/'INSTALLAZIONE.json').write_text(json.dumps({
            'product': PRODUCT, 'installer': 'FREEZE077', 'version': '1.9.0',
            'source_zip_sha256': config['zip_sha256'], 'personal_data_included': False,
            'installed_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        }, indent=2)+'\n')
        if target.exists():
            raise ValueError('La destinazione è comparsa durante l’installazione; non verrà sostituita.')
        staging.rename(target)
        staging = None
        if make_shortcuts:
            shortcuts(target)
        progress(100, 'Pronto. Puoi aprire Wiki22 dall’icona nelle applicazioni.')
        return {'status': 'INSTALLED', 'target': str(target), 'bytes': expanded}
    finally:
        # Only this attempt's temporary files are cleaned; never user data.
        if staging is not None:
            shutil.rmtree(staging)
        lock.rmdir()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--target', type=Path, default=default_target())
    p.add_argument('--silent', action='store_true')
    p.add_argument('--no-shortcuts', action='store_true')
    p.add_argument('--no-launch', action='store_true')
    p.add_argument('--report', type=Path)
    args = p.parse_args()
    def work(progress):
        result = install(args.source, args.target, progress, not args.no_shortcuts)
        if args.report:
            args.report.write_text(json.dumps(result, indent=2)+'\n')
        return result
    from gui import installer_ui
    if args.silent:
        work(lambda p,t: None)
        if not args.no_launch:
            launch(args.target)
    else:
        installer_ui(work, lambda: launch(args.target), args.target)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        if '--silent' not in sys.argv:
            from gui import message
            message('Installazione non completata', str(e), error=True)
        else:
            print(str(e), file=sys.stderr)
        raise SystemExit(1)
