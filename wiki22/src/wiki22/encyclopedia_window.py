"""Wiki22 Linux application window. GTK/WebKit are OS components, not an LLM."""
from pathlib import Path
import threading
from urllib.parse import urlsplit
import webbrowser


def local_navigation(uri, base):
    candidate, origin = urlsplit(uri), urlsplit(base)
    return (candidate.scheme, candidate.netloc) == (origin.scheme, origin.netloc)


def run(root, port):
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('WebKit2', '4.1')
    from gi.repository import Gio, GLib, Gtk, WebKit2
    from .encyclopedia_launcher import ensure_service

    class Wiki22(Gtk.Application):
        def __init__(self):
            super().__init__(application_id='it.progetto22.Wiki22', flags=Gio.ApplicationFlags.FLAGS_NONE)
            self.window = None
            self.url = None
            self.busy = False
            self.load_error = False

        def do_activate(self):
            if self.window is not None:
                self.window.present()
                return
            self.window = Gtk.ApplicationWindow(application=self, title='Wiki22 — Enciclopedia · 22')
            self.window.set_default_size(1200, 850)
            self.window.set_icon_name('wiki22')
            self.stack = Gtk.Stack()
            self.window.add(self.stack)
            panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
            panel.set_halign(Gtk.Align.CENTER)
            panel.set_valign(Gtk.Align.CENTER)
            heading = Gtk.Label()
            heading.set_markup('<span size="xx-large">Wiki22</span>')
            panel.pack_start(heading, False, False, 0)
            panel.pack_start(Gtk.Label(label='Il primo frutto digitale di 22'), False, False, 0)
            self.status = Gtk.Label(label='Apertura della tua enciclopedia…')
            self.status.set_line_wrap(True)
            self.status.set_max_width_chars(70)
            panel.pack_start(self.status, False, False, 0)
            self.retry = Gtk.Button(label='Riprova')
            self.retry.connect('clicked', lambda _: self.start())
            panel.pack_start(self.retry, False, False, 0)
            self.stack.add_named(panel, 'loading')
            manager = WebKit2.WebsiteDataManager.new_ephemeral()
            self.context = WebKit2.WebContext.new_with_website_data_manager(manager)
            self.context.connect('download-started', self.download)
            self.web = WebKit2.WebView.new_with_context(self.context)
            self.web.connect('decide-policy', self.policy)
            self.web.connect('load-failed', self.failed)
            self.web.connect('load-changed', self.loaded)
            self.stack.add_named(self.web, 'encyclopedia')
            self.window.show_all()
            self.start()

        def start(self):
            if self.busy:
                return
            self.busy = True
            self.retry.hide()
            self.status.set_text('Apertura della tua enciclopedia…')
            self.stack.set_visible_child_name('loading')
            def worker():
                try:
                    GLib.idle_add(self.ready, ensure_service(root, port))
                except Exception as exc:
                    GLib.idle_add(self.error, str(exc))
            threading.Thread(target=worker, daemon=True).start()

        def ready(self, url):
            self.busy = False
            self.load_error = False
            self.url = url
            self.web.load_uri(url)
            return False

        def loaded(self, view, event):
            if event == WebKit2.LoadEvent.FINISHED and view.get_uri() == self.url and not self.load_error:
                self.stack.set_visible_child_name('encyclopedia')
                print('Wiki22: finestra pronta · ' + self.url, flush=True)

        def error(self, text):
            self.busy = False
            self.stack.set_visible_child_name('loading')
            self.status.set_text(text)
            self.retry.show()
            return False

        def failed(self, view, event, uri, error):
            # Cancellation is expected when handing an online citation to the browser.
            if self.url and local_navigation(uri, self.url):
                self.load_error = True
                self.error('La pagina non si è aperta. Premi Riprova per riavviare l’accesso.')
            return True

        def policy(self, view, decision, kind):
            if kind in (WebKit2.PolicyDecisionType.NAVIGATION_ACTION, WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION):
                uri = decision.get_navigation_action().get_request().get_uri()
                if self.url and local_navigation(uri, self.url):
                    decision.use()
                else:
                    decision.ignore()
                    if urlsplit(uri).scheme in ('http', 'https'):
                        webbrowser.open(uri)
                return True
            return False

        def download(self, context, download):
            def destination(item, name):
                dialog = Gtk.FileChooserDialog(title='Salva le pagine di Wiki22', parent=self.window,
                                               action=Gtk.FileChooserAction.SAVE)
                dialog.add_buttons('Annulla', Gtk.ResponseType.CANCEL, 'Salva', Gtk.ResponseType.ACCEPT)
                dialog.set_current_name(Path(name).name or 'Wiki22.html')
                dialog.set_do_overwrite_confirmation(True)
                if dialog.run() == Gtk.ResponseType.ACCEPT:
                    item.set_allow_overwrite(True)
                    item.set_destination(Path(dialog.get_filename()).as_uri())
                else:
                    item.cancel()
                dialog.destroy()
                return True
            download.connect('decide-destination', destination)

    return Wiki22().run([])
