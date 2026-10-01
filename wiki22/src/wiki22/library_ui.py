from __future__ import annotations

import queue
import os
import threading
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from wiki22.knowledge.library_registry import LibraryRegistry


PHASE = "WIKI22_PHASE_8C1_DESKTOP_LIBRARY_MANAGEMENT"

BG = "#FFFFFF"
SOFT = "#F8FAFD"
TEXT = "#172033"
MUTED = "#687386"
BLUE = "#2563EB"
BLUE_LIGHT = "#EAF1FF"


def human_size(value: int) -> str:
    size = float(max(0, value))

    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return (
                f"{int(size)} {unit}"
                if unit == "B"
                else f"{size:.1f} {unit}"
            )

        size /= 1024

    return f"{value} B"


class LibraryPanel(tk.Frame):

    def __init__(self, master, *, wiki22_root, on_explore=None):
        super().__init__(master, bg=BG)

        self.on_explore = on_explore
        self.registry = LibraryRegistry(
            Path(wiki22_root).resolve()
        )

        self.registry.ensure()

        self.events = queue.Queue()
        self.busy = False

        self.build()
        self.refresh()

        self.after(150, self.poll_events)

    def build(self):
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", pady=(0, 12))

        self.import_file_btn = tk.Button(
            top,
            text="+ Importa file",
            command=self.import_file,
            bg=BLUE,
            fg="white",
            relief="flat",
            padx=14,
            pady=8,
        )
        self.import_file_btn.pack(side="left")

        self.import_folder_btn = tk.Button(
            top,
            text="+ Importa cartella",
            command=self.import_folder,
            bg=BLUE_LIGHT,
            fg=BLUE,
            relief="flat",
            padx=14,
            pady=8,
        )
        self.import_folder_btn.pack(side="left", padx=8)

        tk.Button(
            top,
            text="Aggiorna",
            command=self.refresh,
            relief="flat",
            padx=12,
            pady=8,
        ).pack(side="right")

        self.status = tk.Label(
            top,
            text="",
            bg=BG,
            fg=MUTED,
        )
        self.status.pack(side="right", padx=12)

        scope = tk.Label(
            self,
            text=(
                "Ambito conoscenza: Libreria singola predefinita"
                "   •   Unificata / Personalizzata disponibili"
            ),
            bg=BLUE_LIGHT,
            fg=TEXT,
            anchor="w",
            padx=12,
            pady=10,
        )
        scope.pack(fill="x", pady=(0, 12))

        columns = (
            "name",
            "status",
            "default",
            "articles",
            "storage",
            "source",
        )

        self.tree = ttk.Treeview(
            self,
            columns=columns,
            show="headings",
            selectmode="browse",
        )

        specs = (
            ("name", "Libreria", 210),
            ("status", "Stato", 90),
            ("default", "Predefinita", 80),
            ("articles", "Articoli", 80),
            ("storage", "Spazio", 100),
            ("source", "Origine", 280),
        )

        for key, label, width in specs:
            self.tree.heading(key, text=label)
            self.tree.column(
                key,
                width=width,
                anchor=(
                    "w"
                    if key in {"name", "source"}
                    else "center"
                ),
            )

        self.tree.pack(
            fill="both",
            expand=True,
        )

        self.tree.bind(
            "<<TreeviewSelect>>",
            lambda _event: self.update_buttons(),
        )

        actions = tk.Frame(self, bg=BG)
        actions.pack(fill="x", pady=(12, 0))

        self.enable_btn = self.button(
            actions,
            "Attiva",
            self.enable_selected,
        )

        self.disable_btn = self.button(
            actions,
            "Disattiva",
            self.disable_selected,
        )

        self.default_btn = self.button(
            actions,
            "Imposta predefinita",
            self.default_selected,
        )

        self.verify_btn = self.button(
            actions,
            "Verifica",
            self.verify_selected,
        )

        self.remove_btn = self.button(
            actions,
            "Rimuovi",
            self.remove_selected,
        )

        if self.on_explore or os.environ.get('WIKI22_MEMIDX_CANDIDATE') == '1':
            self.explore_btn = self.button(actions, 'Esplora', self.explore_selected)

        self.summary = tk.Label(
            self,
            bg=BG,
            fg=MUTED,
            anchor="w",
        )

        self.summary.pack(fill="x", pady=(12, 0))

        tk.Label(
            self,
            text=(
                "Le librerie restano separate. La rimozione elimina solo "
                "la copia di Wiki22 e conserva i file originali."
            ),
            bg=BG,
            fg=MUTED,
            anchor="w",
        ).pack(fill="x", pady=(5, 0))

        self.update_buttons()

    def button(self, parent, text, command):
        b = tk.Button(
            parent,
            text=text,
            command=command,
            bg=SOFT,
            fg=TEXT,
            relief="flat",
            padx=12,
            pady=7,
        )

        b.pack(side="left", padx=(0, 8))

        return b

    def selected_id(self):
        selected = self.tree.selection()
        return str(selected[0]) if selected else None

    def explore_selected(self):
        if self.on_explore:
            row=self.selected_row()
            if row and row.get('enabled'):
                self.on_explore(row['id'])
            else:
                self.status.configure(text='Attiva la libreria per esplorarla.')
            return
        from wiki22.memidx_ui import ExploreWindow
        self.explore_window = ExploreWindow(self, self.registry, self.selected_id())

    def selected_row(self):
        library_id = self.selected_id()
        return (
            self.registry.get(library_id)
            if library_id
            else None
        )

    def refresh(self):
        selected = self.selected_id()

        data = self.registry.load()
        rows = self.registry.list_libraries()
        default_id = data.get("default_library_id")

        for item in self.tree.get_children():
            self.tree.delete(item)

        for row in rows:
            library_id = str(row["id"])

            self.tree.insert(
                "",
                "end",
                iid=library_id,
                values=(
                    row.get("name", library_id),
                    (
                        "Attiva"
                        if row.get("enabled")
                        else "Disattiva"
                    ),
                    (
                        "Sì"
                        if library_id == default_id
                        else ""
                    ),
                    row.get("article_count", 0),
                    human_size(
                        int(row.get("runtime_bytes", row.get("pack_bytes", 0)) or 0)
                    ),
                    row.get("source_name", ""),
                ),
            )

        if selected and self.tree.exists(selected):
            self.tree.selection_set(selected)

        storage = self.registry.storage()

        active = sum(
            1 for row in rows
            if row.get("enabled")
        )

        self.summary.configure(
            text=(
                f"{len(rows)} librerie"
                f"  •  {active} attive"
                f"  •  "
                f"{human_size(storage['total_pack_bytes'])}"
            )
        )

        self.status.configure(
            text=(
                "Pronto"
                if rows
                else "Nessuna libreria installata"
            )
        )

        self.update_buttons()

    def update_buttons(self):
        row = self.selected_row()

        normal = (
            "normal"
            if row is not None and not self.busy
            else "disabled"
        )

        for button in (
            self.enable_btn,
            self.disable_btn,
            self.default_btn,
            self.verify_btn,
            self.remove_btn,
        ):
            button.configure(state=normal)

        if hasattr(self, 'explore_btn'):
            self.explore_btn.configure(state=normal)

        if row is None:
            return

        enabled = bool(row.get("enabled"))

        self.enable_btn.configure(
            state=(
                "disabled"
                if enabled
                else "normal"
            )
        )

        self.disable_btn.configure(
            state=(
                "normal"
                if enabled
                else "disabled"
            )
        )

        self.default_btn.configure(
            state=(
                "normal"
                if enabled
                else "disabled"
            )
        )

    def import_file(self):
        path = filedialog.askopenfilename(
            parent=self.winfo_toplevel(),
            title="Importa una libreria in Wiki22",
            filetypes=(
                (
                    "Conoscenza Wiki22",
                    "*.txt *.md *.json *.jsonl *.ndjson",
                ),
                ("Tutti i file", "*"),
            ),
        )

        if path:
            self.begin_import(Path(path))

    def import_folder(self):
        path = filedialog.askdirectory(
            parent=self.winfo_toplevel(),
            title="Importa una cartella in Wiki22",
        )

        if path:
            self.begin_import(Path(path))

    def begin_import(self, source):
        default_name = (
            source.stem
            if source.is_file()
            else source.name
        )

        name = simpledialog.askstring(
            "Nome della libreria",
            "Assegna un nome a questa libreria:",
            initialvalue=default_name,
            parent=self.winfo_toplevel(),
        )

        if not name:
            return

        self.busy = True

        self.status.configure(
            text=f"Importazione di {name}..."
        )

        self.update_buttons()

        threading.Thread(
            target=self.import_worker,
            args=(source, name),
            daemon=True,
        ).start()

    def import_worker(self, source, name):
        try:
            row = self.registry.import_library(
                source,
                name=name,
            )

            self.events.put(
                ("import_ok", row)
            )

        except Exception as exc:
            self.events.put(
                (
                    "error",
                    "Importazione non riuscita",
                    str(exc),
                )
            )

    def enable_selected(self):
        library_id = self.selected_id()

        if library_id:
            self.registry.set_enabled(
                library_id,
                True,
            )
            self.refresh()

    def disable_selected(self):
        library_id = self.selected_id()

        if library_id:
            self.registry.set_enabled(
                library_id,
                False,
            )
            self.refresh()

    def default_selected(self):
        library_id = self.selected_id()

        if library_id:
            self.registry.set_default(
                library_id
            )
            self.refresh()

    def verify_selected(self):
        library_id = self.selected_id()

        if not library_id:
            return

        result = self.registry.verify(
            library_id
        )

        messagebox.showinfo(
            "Integrità della libreria",
            (
                f"Stato: {result['status']}\n"
                f"Contenuto: {result.get('content_integrity', 'Verifica del file')}\n"
                f"SHA256 corrispondente: "
                f"{result.get('sha256_match')}\n"
                f"Dimensione corrispondente: "
                f"{result.get('bytes_match')}"
            ),
            parent=self.winfo_toplevel(),
        )

    def remove_selected(self):
        library_id = self.selected_id()
        row = self.selected_row()

        if not library_id or row is None:
            return

        if not messagebox.askyesno(
            "Rimuovi libreria",
            (
                f"Rimuovi '{row['name']}'?\n\n"
                "I file originali verranno conservati."
            ),
            parent=self.winfo_toplevel(),
        ):
            return

        self.registry.remove(
            library_id
        )

        self.refresh()

    def poll_events(self):
        try:
            while True:
                event = self.events.get_nowait()

                if event[0] == "import_ok":
                    _, row = event

                    self.busy = False
                    self.refresh()

                    if self.tree.exists(row["id"]):
                        self.tree.selection_set(
                            row["id"]
                        )

                    messagebox.showinfo(
                        "Libreria importata",
                        (
                            f"{row['name']} importata.\n\n"
                            f"Articoli: "
                            f"{row.get('article_count', 0)}\n"
                            f"Spazio: "
                            f"{human_size(int(row.get('pack_bytes', 0)))}"
                        ),
                        parent=self.winfo_toplevel(),
                    )

                elif event[0] == "error":
                    _, title, message = event

                    self.busy = False
                    self.refresh()

                    messagebox.showerror(
                        title,
                        message,
                        parent=self.winfo_toplevel(),
                    )

        except queue.Empty:
            pass

        self.after(
            150,
            self.poll_events,
        )
