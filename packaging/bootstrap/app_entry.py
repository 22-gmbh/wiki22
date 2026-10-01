"""One-icon access; start the bundled backend, then open a desktop window."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import webbrowser

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE/'wiki22/src'))
sys.dont_write_bytecode = True


def personal_profile():
    pointer = BASE/'PROFILE.json'
    if pointer.is_file():
        profile = Path(json.loads(pointer.read_text(encoding='utf-8'))['path'])
        if not profile.is_absolute() or not (profile/'data/libraries/registry.json').is_file():
            raise RuntimeError('La cartella dei tuoi dati precedenti non è disponibile. Ripristinala prima di aprire Wiki22.')
        return profile
    return BASE/'Dati-personali'


def open_window(url):
    data = personal_profile()
    # The backend always uses bundled Python. GTK is just a window host.
    if os.name != 'nt':
        host = Path('/usr/bin/python3')
        if host.is_file():
            check = subprocess.run([str(host), '-c',
                'import gi;gi.require_version("Gtk","3.0");gi.require_version("WebKit2","4.1");from gi.repository import Gtk,WebKit2'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            if check.returncode == 0:
                with (data/'.runtime/window.log').open('ab') as log:
                    proc = subprocess.Popen([str(host), '-B', str(BASE/'window_host.py'), url],
                        stdout=log, stderr=log, start_new_session=True)
                    try:
                        code = proc.wait(timeout=2)
                        if code == 0:
                            return 'GTK_ACTIVATED'
                    except subprocess.TimeoutExpired:
                        return 'GTK_WINDOW'
    browsers = []
    if os.name == 'nt':
        for env in ('PROGRAMFILES(X86)', 'PROGRAMFILES', 'LOCALAPPDATA'):
            prefix = os.environ.get(env)
            if prefix:
                browsers += [Path(prefix)/'Microsoft/Edge/Application/msedge.exe',
                             Path(prefix)/'Google/Chrome/Application/chrome.exe']
    else:
        browsers = [Path(p) for name in ('chromium', 'chromium-browser', 'google-chrome', 'microsoft-edge')
                    if (p := shutil.which(name))]
    for browser in browsers:
        if browser.is_file():
            subprocess.Popen([str(browser), '--app='+url, '--no-first-run',
                              '--user-data-dir='+str(data/'Finestra')],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return 'BROWSER_APP_WINDOW'
    if webbrowser.open(url):
        return 'SYSTEM_BROWSER'
    raise RuntimeError('Non trovo un browser. Installa un browser e riapri Wiki22.')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--no-window', action='store_true')
    p.add_argument('--report', type=Path)
    args = p.parse_args()
    from wiki22.encyclopedia_launcher import ensure_service
    url = ensure_service(personal_profile())
    kind = 'HEADLESS' if args.no_window else open_window(url)
    if args.report:
        args.report.write_text(json.dumps({'url': url, 'view': kind})+'\n')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        from gui import message
        message('Wiki22 non si è aperto', str(exc), error=True)
        raise SystemExit(1)
