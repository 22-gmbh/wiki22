"""Reuse Wiki22's GTK window without sharing the installed 1.0 application ID."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent/'wiki22/src'))
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('WebKit2', '4.1')
from gi.repository import Gio
from wiki22 import encyclopedia_launcher, encyclopedia_window

# Backend was started by bundled Python before this UI-only process.
url = sys.argv[1]
encyclopedia_launcher.ensure_service = lambda root, port: url
# The frozen window's run() imports Gio dynamically. Wrap only its application
# constructor locally to give this separate edition its own desktop identity.
# Do not monkeypatch GI global classes. Load a narrowly adjusted window module.
source = Path(encyclopedia_window.__file__).read_text(encoding='utf-8')
source = source.replace("application_id='it.progetto22.Wiki22'", "application_id='it.progetto22.Wiki22.Enciclopedia'")
code = compile(source, str(encyclopedia_window.__file__), 'exec')
namespace = {'__name__': 'wiki22.share_window', '__package__': 'wiki22'}
exec(code, namespace)
raise SystemExit(namespace['run'](Path(__file__).resolve().parent/'Dati-personali', 8765))
