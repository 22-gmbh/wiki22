"""Stable Linux entry point: serialized startup, detached service, ready handshake."""
import argparse

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import ProxyHandler, build_opener

from .encyclopedia_service import VERSION


def running_url(root):
    try:
        record = json.loads((root / '.runtime/encyclopedia-server.json').read_text())
        port = record['port']
        if type(port) is not int or not 1 <= port <= 65535:
            return None
        url = f'http://127.0.0.1:{port}/'
        with build_opener(ProxyHandler({})).open(url + 'api/health', timeout=.7) as response:
            health = json.load(response)
        if health == dict(version=VERSION, root=str(root)):
            return url
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return None


def ensure_service(root, port=8765, timeout=30):
    root = Path(root).resolve()
    state = root / '.runtime'
    state.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    with (state / 'encyclopedia-launch.lock').open('a') as lock:
        while True:
            try:
                if os.name == 'nt':
                    import msvcrt
                    if lock.seek(0, 2) == 0:
                        lock.write('0'); lock.flush()
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (11, 13):
                    raise
                if time.monotonic() >= deadline:
                    raise RuntimeError('Un altro avvio è ancora in corso. Attendi e riapri Wiki22.')
                time.sleep(.1)
        url = running_url(root)
        if url:
            return url
        log_path = state / 'encyclopedia-startup.log'
        # This diagnostic file contains no personal readings. Bound it on startup.
        mode = 'wb' if log_path.exists() and log_path.stat().st_size > 1024 * 1024 else 'ab'
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1',
                   PYTHONPATH=str(Path(__file__).resolve().parents[1]))
        flags = dict(creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP) if os.name == 'nt' else dict(start_new_session=True)
        entry = 'import sys,runpy;sys.path.insert(0,sys.argv.pop(1));runpy.run_module("wiki22.encyclopedia_app",run_name="__main__")'
        with log_path.open(mode) as log:
            process = subprocess.Popen(
                [sys.executable, '-X', 'utf8', '-B', '-c', entry, str(Path(__file__).resolve().parents[1]), '--root', str(root),
                 '--port', str(port), '--no-browser'], env=env, cwd=str(root),
                stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                **flags, close_fds=True)
        while time.monotonic() < deadline:
            url = running_url(root)
            if url:
                return url
            if process.poll() is not None:
                raise RuntimeError(f'Wiki22 non è partito. Dettagli: {log_path}')
            time.sleep(.1)
        # Only our own unready child is stopped; never terminate an existing service.
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise RuntimeError(f'Avvio non completato entro {timeout} secondi. Dettagli: {log_path}')


def main():
    parser = argparse.ArgumentParser(description='Wiki22 — il primo frutto digitale di 22')
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-window', action='store_true', help='Avvia il servizio e stampa il link')
    parser.add_argument('--browser', action='store_true', help='Apri nel browser di sistema')
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error('Porta non valida')
    if args.no_window or args.browser:
        url = ensure_service(args.root, args.port)
        print(url, flush=True)
        if args.browser:
            import webbrowser
            if not webbrowser.open(url):
                raise RuntimeError('Apri il link mostrato nel tuo browser.')
        return 0
    from .encyclopedia_window import run
    return run(args.root, args.port)


if __name__ == '__main__':
    raise SystemExit(main())
