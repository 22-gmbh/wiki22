"""Relocatable recipient entry. All personal writes stay in Dati-personali."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import sys
from urllib.request import build_opener, ProxyHandler, Request
import webbrowser

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE / 'wiki22/src'))
sys.dont_write_bytecode = True


def main():
    parser = argparse.ArgumentParser(description='Wiki22 1.7 — Wikipedia pronta da leggere')
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        raise ValueError('Porta non valida')
    if args.verify:
        records = json.loads((BASE/'INTEGRITA.json').read_text(encoding='utf-8'))
        for name, expected in records.items():
            p = BASE/name
            if not p.is_file():
                raise ValueError('File mancante: ' + name)
            with p.open('rb') as f:
                actual = hashlib.file_digest(f, 'sha256').hexdigest()
            if actual != expected['sha256']:
                raise ValueError('File modificato: ' + name)
        print(f'Integrità verificata: {len(records)} file.')
        return 0
    from wiki22.encyclopedia_launcher import ensure_service, running_url
    root = BASE/'Dati-personali'
    if args.stop:
        url = running_url(root)
        if not url:
            print('Wiki22 è già chiuso.')
            return 0
        opener = build_opener(ProxyHandler({}))
        with opener.open(url, timeout=3) as response:
            html = response.read().decode('utf-8')
        token = re.search(r'name="wiki22-token" content="([^"]+)"', html)[1]
        request = Request(url+'api/shutdown', data=b'{}',
            headers={'Content-Type':'application/json', 'X-Wiki22-Token':token})
        with opener.open(request, timeout=5) as response:
            json.load(response)
        print('Wiki22 è stato chiuso. Ora puoi spostare la cartella.')
        return 0
    # Factory registry is restored only if absent; never replace a user's imports.
    registry = root/'data/libraries/registry.json'
    if not registry.is_file():
        raise ValueError('Registro iniziale mancante: estrai di nuovo lo ZIP originale in una nuova cartella.')
    url = ensure_service(root, port=args.port)
    print('Wiki22 è pronto: ' + url, flush=True)
    if not args.no_browser and not webbrowser.open(url):
        print('Apri questo indirizzo nel tuo browser. Non serve Internet.', flush=True)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print('Non riesco ad aprire Wiki22: ' + str(exc), file=sys.stderr)
        print('Estrai tutta la cartella in Documenti, in una posizione dove puoi scrivere.', file=sys.stderr)
        raise SystemExit(1)
