from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from wiki22.library_ui import LibraryPanel
from wiki22.scope_ui import ScopeSelector
from wiki22.source_attribution import attribute_source_records
from wiki22.product_locale import NATIVE_LANGUAGE, TAGLINE


PHASE = "WIKI22_PHASE_8E_MULTI_LIBRARY_SOURCE_ATTRIBUTION"

PACKAGE_DIR = Path(__file__).resolve().parent
SRC_DIR = PACKAGE_DIR.parent
WIKI22_DIR = SRC_DIR.parent
ROOT = WIKI22_DIR.parent

RUNNER = ROOT / "run_wiki22.sh"
HEALTH_RUNNER = ROOT / "run_health.sh"

NAVY = "#0B1630"
NAVY_LIGHT = "#142445"
BLUE = "#2563EB"
BLUE_LIGHT = "#EAF1FF"
SURFACE = "#FFFFFF"
BACKGROUND = "#F4F7FB"
TEXT = "#172033"
MUTED = "#687386"
BORDER = "#DDE4EE"
GREEN = "#15803D"
GREEN_BG = "#EAF7EF"
ORANGE = "#B45309"
ORANGE_BG = "#FFF4E5"


def clean_terminal_output(value: str) -> str:
    ansi = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
    return ansi.sub("", value).replace("\r", "").strip()


def _decode_fragment(value: str) -> str:
    try:
        return json.loads(
            '"' + value + '"'
        )
    except Exception:
        return (
            value
            .replace(r'\"', '"')
            .replace(r'\\', '\\')
        )


def _evidence_section(raw: str) -> str:
    cleaned = clean_terminal_output(raw)

    match = re.search(
        r"(?im)^\s*SUPPORTING EVIDENCE\b",
        cleaned,
    )

    if match:
        return cleaned[match.end():]

    return cleaned


QUERY_TIMEOUT_SECONDS = 180

INSUFFICIENT = "Non riesco a ricavare una risposta verificata dalle fonti locali. Questo non significa che l’informazione sia assente: puoi cercarla in Esplora."


def _json_section(raw, label):
    match = re.search(r"(?m)^\s*" + re.escape(label) + r"\s*$", raw)
    if not match:
        return None
    tail = raw[match.end():].lstrip("= \n\r")
    try:
        return json.JSONDecoder().raw_decode(tail)[0]
    except (ValueError, TypeError):
        return None


def extract_source_records(
    raw: str,
) -> list[dict[str, object]]:
    """
    Extract human-readable evidence records from Wiki22 CLI output.

    Internal paths, CLI prompts and serialized diagnostic structure are
    intentionally excluded from the product-facing Sources view.
    """
    structured = _json_section(raw, "SUPPORTING EVIDENCE")
    if isinstance(structured, list):
        return [dict(row) for row in structured if isinstance(row, dict) and row.get("text")]

    section = _evidence_section(raw)

    # CLI currently may contain nested / escaped JSON fragments.
    normalized = section

    for _ in range(3):
        updated = normalized.replace(
            r'\"',
            '"',
        )

        if updated == normalized:
            break

        normalized = updated

    records: list[dict[str, object]] = []
    seen: set[str] = set()

    text_pattern = re.compile(
        r'"text"\s*:\s*"((?:\\.|[^"\\])*)"',
        re.DOTALL,
    )

    score_pattern = re.compile(
        r'"score"\s*:\s*(-?\d+(?:\.\d+)?)',
        re.DOTALL,
    )

    path_pattern = re.compile(
        r'"path"\s*:\s*"((?:\\.|[^"\\])*)"',
        re.DOTALL,
    )

    for match in text_pattern.finditer(
        normalized
    ):
        raw_text = match.group(1)

        body = _decode_fragment(
            raw_text
        ).strip()

        if not body:
            continue

        low = body.lower()

        if low in {
            "wiki22",
            "session closed.",
            "answer",
        }:
            continue

        # Find nearest metadata before this text value.
        prefix = normalized[
            max(0, match.start() - 1200):
            match.start()
        ]

        scores = list(
            score_pattern.finditer(prefix)
        )

        paths = list(
            path_pattern.finditer(prefix)
        )

        score: float | None = None
        ref: str | None = None

        if scores:
            try:
                score = float(
                    scores[-1].group(1)
                )
            except ValueError:
                score = None

        if paths:
            ref = _decode_fragment(
                paths[-1].group(1)
            ).strip()

        # Normalize whitespace without destroying readable paragraphs.
        body = re.sub(
            r"[ \t]+",
            " ",
            body,
        )

        body = re.sub(
            r"\n{3,}",
            "\n\n",
            body,
        )

        fingerprint = re.sub(
            r"\W+",
            "",
            body.lower(),
        )[:500]

        if not fingerprint:
            continue

        if fingerprint in seen:
            continue

        seen.add(
            fingerprint
        )

        records.append(
            {
                "text": body,
                "score": score,
                "reference": ref,
            }
        )

    return records


def format_source_records(
    records: list[dict[str, object]],
) -> str:

    if not records:
        return (
            "Nessuna evidenza locale di supporto "
            "è disponibile per l'ultima risposta."
        )

    blocks: list[str] = []

    for index, record in enumerate(
        records,
        start=1,
    ):

        body = str(
            record.get("text")
            or ""
        ).strip()

        score = record.get(
            "score"
        )

        library = str(
            record.get(
                "library_name"
            )
            or ""
        ).strip()

        article = str(
            record.get(
                "article_title"
            )
            or ""
        ).strip()

        document = str(
            record.get(
                "source"
            )
            or ""
        ).strip()

        lines = [
            f"Fonte {index}",
            "─" * 72,
        ]

        if library:
            lines.append(
                f"Libreria: {library}"
            )

        if article:
            lines.append(
                f"Articolo: {article}"
            )

        if document:
            lines.append(
                f"Documento: {document}"
            )

        if record.get('original_revision_url'):
            lines.append('Revisione Wikipedia: ' + str(record['original_revision_url']))

        if isinstance(
            score,
            (
                int,
                float,
            ),
        ):
            lines.append(
                f"Rilevanza: {score:g}"
            )

        lines.append("")
        lines.append(body)

        blocks.append(
            "\n".join(lines)
        )

    return "\n\n".join(
        blocks
    )






def extract_sources(raw: str) -> str:
    """
    Backward-compatible product-facing Sources formatter.
    """
    return format_source_records(
        extract_source_records(raw)
    )


def parse_user_answer(
    raw: str,
    query: str = "",
) -> str:
    """
    Convert Wiki22 CLI output into product-facing answer text.

    CLI banners, echoed questions, separators, diagnostics,
    prompts and source blocks are never exposed in Chat.
    """
    structured = _json_section(raw, "ANSWER")
    if isinstance(structured, dict) and "status" in structured:
        if structured.get("status") in {"ANSWERED", "READING", "CLARIFY"} and isinstance(structured.get("answer"), str):
            return structured["answer"]
        related = structured.get("related_articles", [])
        titles = [x.get("title") for x in related if isinstance(x, dict) and isinstance(x.get("title"), str)]
        if titles:
            names = ', '.join('«' + title + '»' for title in titles[:3])
            return "Non riesco a ricavare una risposta verificata. Ho trovato " + names + ": puoi consultare la voce in Esplora."
        return INSUFFICIENT

    cleaned = clean_terminal_output(raw)

    if not cleaned:
        return (
            "Wiki22 non ha restituito una risposta."
        )

    # Sources are rendered separately.
    evidence_match = re.search(
        r"(?im)^\s*SUPPORTING EVIDENCE\b",
        cleaned,
    )

    if evidence_match:
        cleaned = cleaned[
            :evidence_match.start()
        ]

    lines = cleaned.splitlines()

    result: list[str] = []

    skip_next_user_line = False
    json_depth = 0

    ignored_exact = {
        "answer",
        "wiki22",
        "you",
        "wiki22>",
        "wiki22 v0.1",
        "offline local knowledge interface.",
        "type 'help' for commands.",
        'type "help" for commands.',
        "diagnostics",
        "quit",
    }

    technical_keys = {
        "provider_health",
        "provider",
        "synthetic",
        "pack_path",
        "evidence_units",
        "production",
        "product",
        "offline",
        "network",
        "version",
        "runtime",
        "runtime_source_count",
        "rc_id",
        "rc_sha",
        "ai22_decision",
    }

    for raw_line in lines:
        line = raw_line.strip()

        if not line:
            if result and result[-1] != "":
                result.append("")
            continue

        low = line.lower()

        # Visual CLI separators.
        if re.fullmatch(
            r"[=\-_]{5,}",
            line,
        ):
            continue

        # Shell prompt.
        if re.fullmatch(
            r"wiki22>\s*",
            line,
            flags=re.IGNORECASE,
        ):
            continue

        # Echoed user question.
        if low == "you":
            skip_next_user_line = True
            continue

        if skip_next_user_line:
            if query:
                if line.strip() == query.strip():
                    skip_next_user_line = False
                    continue

            # CLI normally prints exactly one line after YOU.
            skip_next_user_line = False
            continue

        if low in ignored_exact:
            continue

        # Remove explicit query echo even without YOU marker.
        if (
            query
            and line.strip() == query.strip()
        ):
            continue

        # JSON diagnostic objects.
        if line.startswith("{"):
            json_depth += line.count("{")
            json_depth -= line.count("}")

            if json_depth < 0:
                json_depth = 0

            continue

        if json_depth > 0:
            json_depth += line.count("{")
            json_depth -= line.count("}")

            if json_depth < 0:
                json_depth = 0

            continue

        if (
            line.startswith('"')
            and '":' in line
        ):
            continue

        if line in {
            "}",
            "},",
            "]",
            "],",
        }:
            continue

        normalized_key = (
            low
            .strip('", ')
            .split(":", 1)[0]
            .strip()
        )

        if normalized_key in technical_keys:
            continue

        # Local-path / implementation leakage.
        if any(
            token in low
            for token in (
                "/home/",
                "syntheticprovider",
                "controlled_pack_",
                ".runtime/",
                "rc_preparation/",
            )
        ):
            continue

        result.append(line)

    while result and not result[0]:
        result.pop(0)

    while result and not result[-1]:
        result.pop()

    answer = "\n".join(
        result
    ).strip()

    # Fail product-facing, not terminal-facing.
    if not answer:
        return (
            INSUFFICIENT
        )

    # A surviving block that is only CLI metadata is not an answer.
    meaningful = [
        line
        for line in answer.splitlines()
        if len(line.split()) >= 3
    ]

    if not meaningful:
        return (
            INSUFFICIENT
        )

    return answer


def count_supporting_sources(raw: str) -> int:
    return len(
        extract_source_records(raw)
    )


def discover_local_knowledge() -> list[tuple[str, str, int, str]]:
    rows: list[tuple[str, str, int, str]] = []

    excluded = {
        ".venv",
        ".runtime",
        "__pycache__",
        ".git",
        "rc_preparation",
        "evidence",
        "tests",
    }

    allowed = {
        ".json",
        ".jsonl",
        ".txt",
        ".md",
    }

    for path in WIKI22_DIR.rglob("*"):
        if not path.is_file():
            continue

        relative = path.relative_to(WIKI22_DIR)

        if any(part in excluded for part in relative.parts):
            continue

        if path.suffix.lower() not in allowed:
            continue

        low = relative.as_posix().lower()

        if not any(
            token in low
            for token in (
                "knowledge",
                "pack",
                "article",
                "source",
                "library",
                "data",
            )
        ):
            continue

        try:
            size = path.stat().st_size
        except OSError:
            size = 0

        rows.append(
            (
                path.name,
                path.suffix.lower().lstrip(".").upper() or "FILE",
                size,
                relative.as_posix(),
            )
        )

    rows.sort(key=lambda row: row[3])
    return rows[:500]


class Wiki22Desktop(tk.Tk):
    def __init__(self) -> None:
        super().__init__()

        self.title("Wiki22")
        self.geometry("1280x820")
        self.minsize(1080, 700)
        self.configure(bg=BACKGROUND)

        self.events: queue.Queue = queue.Queue()
        from wiki22.workspace_state import WorkspaceState
        self.workspace=WorkspaceState(WIKI22_DIR)
        from wiki22.research_journey import ResearchJourney
        self.journey=ResearchJourney()
        self.current_page='Chat'
        if self.workspace.preferences()['remember_searches']:
            recent=self.workspace.recent(limit=1)
            if recent:self.journey.activate(recent[0]['topic'],recent[0]['scope'],recent[0]['query'])
        from wiki22.learning_background import LearningCoordinator
        self.learning_coordinator=LearningCoordinator(WIKI22_DIR)
        from wiki22.query_client import WarmQueryClient
        self.query_client = WarmQueryClient(ROOT, WIKI22_DIR, timeout=QUERY_TIMEOUT_SECONDS)

        self.nav_buttons = {}
        self.pages = {}

        self.status_engine = tk.StringVar(value="Verifica...")
        self.status_network = tk.StringVar(value="Verifica...")
        self.status_offline = tk.StringVar(value="Verifica...")
        self.status_mode = tk.StringVar(value="Locale / Linux")

        self._configure_ttk()
        self._build_shell()
        self._build_chat()
        self._build_sources()
        self._build_library()
        self._build_settings()
        self._build_self_status()
        self._build_learning()
        self._build_research()
        self._build_study()
        self._build_history()
        self._build_maps()

        self.nav_buttons["Chat"].configure(
            text="Chat"
        )
        self.nav_buttons["Sources"].configure(
            text="Fonti"
        )
        self.nav_buttons["Library"].configure(
            text="Librerie"
        )
        self.nav_buttons["Settings"].configure(
            text="Impostazioni"
        )

        self.show_page("Chat")

        self.memory_ready=False
        self.ask_button.configure(state='disabled')
        self.chat_status.configure(text='Preparazione della memoria… Puoi intanto aprire Studio.',bg=ORANGE_BG,fg=ORANGE)
        threading.Thread(target=self._warmup_worker,daemon=True).start()

        self.after(100, self._poll_events)

        threading.Thread(
            target=self._health_worker,
            daemon=True,
        ).start()

    def destroy(self):
        learner=self.__dict__.get('learning_coordinator')
        if learner:learner.close()
        client = self.__dict__.get('query_client')
        if client is not None:
            client.close()
        # Cancel root and LibraryPanel polling callbacks before Tcl commands
        # disappear. A later Desktop session must not inherit dead callbacks.
        for callback in self.tk.splitlist(self.tk.call("after", "info")):
            # Cancel scheduling only; each owning widget deletes its own
            # Tcl callback command during destruction.
            self.tk.call("after", "cancel", callback)
        super().destroy()

    def _configure_ttk(self) -> None:
        style = ttk.Style(self)

        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TFrame", background=BACKGROUND)
        style.configure("TLabel", background=BACKGROUND, foreground=TEXT, font=("DejaVu Sans", 10))
        style.configure("TButton", font=("DejaVu Sans", 10), padding=(12, 7))

        style.configure(
            "Wiki.Treeview",
            background=SURFACE,
            fieldbackground=SURFACE,
            foreground=TEXT,
            rowheight=30,
            borderwidth=0,
            font=("DejaVu Sans", 10),
        )

        style.configure(
            "Wiki.Treeview.Heading",
            background="#EEF2F7",
            foreground=TEXT,
            font=("DejaVu Sans", 10, "bold"),
            relief="flat",
        )

    def _build_shell(self) -> None:
        sidebar = tk.Frame(
            self,
            bg=NAVY,
            width=228,
        )
        sidebar.pack(
            side="left",
            fill="y",
        )
        sidebar.pack_propagate(False)

        self.sidebar = sidebar

        self.content = tk.Frame(
            self,
            bg=BACKGROUND,
        )
        self.content.pack(
            side="left",
            fill="both",
            expand=True,
        )

        brand = tk.Frame(
            sidebar,
            bg=NAVY,
        )
        brand.pack(
            fill="x",
            padx=22,
            pady=(26, 34),
        )

        tk.Label(
            brand,
            text="Wiki22",
            bg=NAVY,
            fg="white",
            font=("DejaVu Sans", 22, "bold"),
            anchor="w",
        ).pack(fill="x")

        tk.Label(
            brand,
            text="Conoscenza. Offline. Tua.",
            bg=NAVY,
            fg="#A9B8D4",
            font=("DejaVu Sans", 9),
            anchor="w",
        ).pack(
            fill="x",
            pady=(4, 0),
        )

        for name in (
            "Chat",
            "Sources",
            "Library",
            "Explore",
            "Study",
            "Articles",
            "Maps",
            "Learning",
            "History",
            "State",
            "Settings",
        ):
            button = tk.Button(
                sidebar,
                text={
                    "Chat": "Chat",
                    "Sources": "Fonti",
                    "Library": "Librerie",
                    "Explore": "Esplora",
                    "Study": "Studio",
                    "Articles": "Enciclopedia",
                    "Maps": "Mappe mentali",
                    "History": "Ricerche",
                    "Learning": "Capacità e memoria",
                    "State": "Wiki22 / Stato",
                    "Settings": "Impostazioni",
                }.get(name, name),
                command=lambda page=name: self.show_page(page),
                bg=NAVY,
                fg="#CAD4E8",
                highlightthickness=0,
                activebackground=NAVY_LIGHT,
                activeforeground="white",
                relief="flat",
                bd=0,
                anchor="w",
                padx=22,
                pady=12,
                font=("DejaVu Sans", 11),
            )
            button.pack(
                fill="x",
                padx=10,
                pady=2,
            )

            self.nav_buttons[name] = button

        spacer = tk.Frame(
            sidebar,
            bg=NAVY,
        )
        spacer.pack(
            fill="both",
            expand=True,
        )

        status_box = tk.Frame(
            sidebar,
            bg=NAVY_LIGHT,
        )
        status_box.pack(
            fill="x",
            padx=14,
            pady=16,
        )

        tk.Label(
            status_box,
            text="●  OFFLINE",
            bg=NAVY_LIGHT,
            fg="#75D69C",
            font=("DejaVu Sans", 10, "bold"),
            anchor="w",
        ).pack(
            fill="x",
            padx=12,
            pady=(10, 3),
        )

        tk.Label(
            status_box,
            text="Motore locale AI22",
            bg=NAVY_LIGHT,
            fg="#A9B8D4",
            font=("DejaVu Sans", 9),
            anchor="w",
        ).pack(
            fill="x",
            padx=12,
            pady=(0, 10),
        )

    def _make_page(self, name: str, title: str, subtitle: str):
        page = tk.Frame(
            self.content,
            bg=BACKGROUND,
        )

        page.place(
            relx=0,
            rely=0,
            relwidth=1,
            relheight=1,
        )

        header = tk.Frame(
            page,
            bg=BACKGROUND,
        )
        header.pack(
            fill="x",
            padx=36,
            pady=(28, 18),
        )

        tk.Label(
            header,
            text=title,
            bg=BACKGROUND,
            fg=TEXT,
            font=("DejaVu Sans", 23, "bold"),
            anchor="w",
        ).pack(fill="x")

        tk.Label(
            header,
            text=subtitle,
            bg=BACKGROUND,
            fg=MUTED,
            font=("DejaVu Sans", 10),
            anchor="w",
        ).pack(
            fill="x",
            pady=(5, 0),
        )

        self.pages[name] = page
        return page

    def show_page(self, name: str) -> None:
        page = self.pages.get(name)

        if page is None:
            return

        self.current_page=name
        if name in {'Study','Articles','Maps'}:self.resume_journey(name)
        page.tkraise()

        for page_name, button in self.nav_buttons.items():
            button.configure(
                bg=NAVY_LIGHT if page_name == name else NAVY,
                fg="white" if page_name == name else "#CAD4E8",
            )

        if name == "History":self.history_panel.refresh()
        if name == "Learning" and not self.learning_panel.busy:self.learning_panel.refresh()

        if name in {'Explore','Articles','Maps'}:
            panel = {'Explore':self.atlas_panel,'Articles':self.articles_panel,'Maps':self.maps_panel}[name]
            panel.scope.refresh()

        if name == "Library":
            self.refresh_library()

        if name == "Chat":
            selector = getattr(
                self,
                "scope_selector",
                None,
            )

            if selector is not None:
                selector.refresh()

    def _build_chat(self) -> None:
        page = self._make_page(
            "Chat",
            "Chat",
            "Interroga la tua conoscenza locale. Wiki22 risponde offline e mantiene separate le fonti.",
        )

        self.scope_selector = ScopeSelector(
            page,
            wiki22_root=WIKI22_DIR,
        )

        self.scope_selector.pack(
            fill="x",
            padx=36,
            pady=(0, 12),
        )

        actions=ttk.Frame(page);actions.pack(fill='x',padx=36,pady=(0,10))
        self.topic_choice=tk.StringVar()
        self.topic_combo=ttk.Combobox(actions,textvariable=self.topic_choice,state='readonly',width=34)
        self.topic_combo.pack(side='left',fill='x',expand=True)
        ttk.Button(actions,text='Studia argomento',command=lambda:self.open_current('Study')).pack(side='left',padx=6)
        ttk.Button(actions,text='Pagina enciclopedica',command=lambda:self.open_current('Articles')).pack(side='left')
        ttk.Button(actions,text='Ricerche recenti',command=lambda:self.show_page('History')).pack(side='left',padx=6)

        card = tk.Frame(
            page,
            bg=SURFACE,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        card.pack(
            fill="both",
            expand=True,
            padx=36,
            pady=(0, 22),
        )

        top = tk.Frame(
            card,
            bg=SURFACE,
        )
        top.pack(
            fill="x",
            padx=24,
            pady=(18, 10),
        )

        tk.Label(
            top,
            text="Conversazione AI locale",
            bg=SURFACE,
            fg=TEXT,
            font=("DejaVu Sans", 11, "bold"),
        ).pack(side="left")

        self.chat_status = tk.Label(
            top,
            text="Pronto",
            bg=GREEN_BG,
            fg=GREEN,
            font=("DejaVu Sans", 9, "bold"),
            padx=10,
            pady=5,
        )
        self.chat_status.pack(side="right")

        frame = tk.Frame(
            card,
            bg=SURFACE,
        )
        frame.pack(
            fill="both",
            expand=True,
            padx=24,
        )

        scroll = tk.Scrollbar(frame)
        scroll.pack(
            side="right",
            fill="y",
        )

        self.chat_output = tk.Text(
            frame,
            wrap="word",
            bg=SURFACE,
            fg=TEXT,
            relief="flat",
            font=("DejaVu Sans", 10),
            yscrollcommand=scroll.set,
            state="disabled",
        )
        self.chat_output.pack(
            fill="both",
            expand=True,
        )

        scroll.config(
            command=self.chat_output.yview
        )

        self.chat_output.tag_configure(
            "user_label",
            foreground=BLUE,
            font=("DejaVu Sans", 9, "bold"),
        )

        self.chat_output.tag_configure(
            "assistant_label",
            foreground=GREEN,
            font=("DejaVu Sans", 9, "bold"),
        )

        self.chat_output.tag_configure(
            "text",
            foreground=TEXT,
            font=("DejaVu Sans", 10),
            spacing3=12,
        )

        self._append_chat(
            "assistant_label",
            "WIKI22",
        )

        self._append_chat(
            "text",
            "Chiedimi un fatto, una spiegazione o un confronto. Puoi proseguire sullo stesso argomento, aprirne la pagina enciclopedica o studiarlo senza riscriverlo. Le ricerche restano consultabili in Ricerche.",
        )

        composer = tk.Frame(
            card,
            bg="#F8FAFD",
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        composer.pack(
            fill="x",
            padx=24,
            pady=20,
        )

        self.query_box = tk.Text(
            composer,
            height=3,
            wrap="word",
            relief="flat",
            bg="#F8FAFD",
            fg=TEXT,
            font=("DejaVu Sans", 10),
        )
        self.query_box.pack(
            side="left",
            fill="both",
            expand=True,
            padx=10,
            pady=10,
        )

        self.query_box.bind(
            "<Control-Return>",
            lambda _event: self.submit_query(),
        )

        self.ask_button = tk.Button(
            composer,
            text="Chiedi a Wiki22",
            command=self.submit_query,
            bg=BLUE,
            fg="white",
            relief="flat",
            padx=18,
            pady=10,
            font=("DejaVu Sans", 10, "bold"),
        )
        self.ask_button.pack(
            side="right",
            padx=10,
            pady=10,
        )

    def _append_chat(self, tag: str, value: str) -> None:
        self.chat_output.configure(state="normal")
        self.chat_output.insert("end", value + "\n", tag)
        self.chat_output.configure(state="disabled")
        self.chat_output.see("end")

    def submit_query(self) -> None:
        if not getattr(self,"memory_ready",True):return
        if getattr(self, "query_busy", False):
            return
        query = self.query_box.get(
            "1.0",
            "end",
        ).strip()

        if not query:
            return

        self.query_busy = True
        self.query_state = None
        self.last_query = query

        self._append_chat(
            "user_label",
            "TU",
        )

        self._append_chat(
            "text",
            query,
        )

        self.query_box.delete(
            "1.0",
            "end",
        )

        self.ask_button.configure(
            state="disabled"
        )

        self.chat_status.configure(
            text="Elaborazione locale...",
            bg=ORANGE_BG,
            fg=ORANGE,
        )

        scope_env = {}

        selector = getattr(
            self,
            "scope_selector",
            None,
        )

        if selector is not None:
            scope_env = selector.environment()
            self.last_scope_ids = list(
                getattr(
                    selector,
                    "current_ids",
                    [],
                )
            )

        # Preserve the exact scope snapshot used by this query.
        # The result attribution path must use the same scope.
        self.last_scope_env = dict(scope_env)
        # A short title can travel immediately, even while chat is answering.
        if len(query)<=180 and not any(c in query for c in '?!.\n'):
            self.journey.activate(query,getattr(self,'last_scope_ids',[]),query)


        threading.Thread(
            target=self._query_worker,
            args=(
                query,
                scope_env,
            ),
            daemon=True,
        ).start()

    def _query_worker_impl(self, query: str, scope_env: dict[str, str]) -> None:
        response = self.query_client.query(query, dict(scope_env))
        self.events.put(('query', 0, response['raw']))


    def _query_worker(self, query, scope_env):
        """Fail-safe wrapper around the local CLI query."""
        try:
            return self._query_worker_impl(query, scope_env)
        except subprocess.TimeoutExpired as exc:
            timeout = getattr(exc, 'timeout', 'unknown')
            raw = f"TIMEOUT: local Wiki22 query exceeded {timeout} seconds"
            self.events.put(("query", 124, raw))
        except Exception as exc:
            raw = f"ERROR: {type(exc).__name__}: {exc}"
            self.events.put(("query", 1, raw))

    def _build_sources(self) -> None:
        page = self._make_page(
            "Sources",
            "Fonti",
            "Evidenze a supporto dell'ultima risposta. La diagnostica tecnica resta separata.",
        )

        card = tk.Frame(
            page,
            bg=SURFACE,
            highlightbackground=BORDER,
            highlightthickness=1,
        )
        card.pack(
            fill="both",
            expand=True,
            padx=36,
            pady=(0, 22),
        )

        self.sources_output = tk.Text(
            card,
            wrap="word",
            bg="#F8FAFD",
            fg=TEXT,
            relief="flat",
            font=("DejaVu Sans Mono", 9),
            state="disabled",
        )
        self.sources_output.pack(
            fill="both",
            expand=True,
            padx=22,
            pady=22,
        )

        self._set_sources(
            "Fai una domanda nella Chat per visualizzare le fonti di supporto."
        )

    def _set_sources(self, value: str) -> None:
        self.sources_output.configure(state="normal")
        self.sources_output.delete("1.0", "end")
        self.sources_output.insert("1.0", value)
        self.sources_output.configure(state="disabled")

    def _build_library(self) -> None:
        page = self._make_page(
            "Library",
            "Librerie",
            (
                "Importa e gestisci le librerie locali. "
                "Wikipedia è facoltativa."
            ),
        )

        self.library_panel = LibraryPanel(
            page,
            wiki22_root=WIKI22_DIR,
            on_explore=self._open_library_atlas,
        )

        self.library_panel.pack(
            fill="both",
            expand=True,
            padx=36,
            pady=(0, 22),
        )

    def refresh_library(self) -> None:
        panel = getattr(
            self,
            "library_panel",
            None,
        )

        if panel is not None:
            panel.refresh()

    def _open_library_atlas(self, library_id):
        self.show_page('Explore')
        panel=self.atlas_panel
        panel.scope.current_mode='SINGLE'
        panel.scope.current_ids=[library_id]
        for label,(mode,ids) in panel.scope.option_map.items():
            if mode=='SINGLE' and ids==[library_id]:
                panel.scope.choice.set(label)
                break
        panel.view.set('Alfabetico')
        panel.topic.set('')
        panel.run()

    def _build_research(self):
        from wiki22.research_ui import ResearchPanel
        page=self._make_page('Explore','Esplora','Segui le connessioni e torna sempre alle fonti.')
        self.atlas_panel=ResearchPanel(page,wiki22_root=WIKI22_DIR,mode='atlas',on_topic=self.record_research)
        self.atlas_panel.pack(fill='both',expand=True,padx=36,pady=(0,22))
        from wiki22.encyclopedia_ui import EncyclopediaPanel
        page=self._make_page('Articles','Enciclopedia','Pagine di ricerca con fonti numerate: scegli da una a dodici pagine.')
        self.articles_panel=EncyclopediaPanel(page,wiki22_root=WIKI22_DIR,on_topic=self.record_research,on_navigate=self.navigate_topic)
        self.articles_panel.pack(fill='both',expand=True,padx=36,pady=(0,22))

    def _build_maps(self):
        from wiki22.mindmap_ui import MindMapPanel
        page=self._make_page('Maps','Mappe mentali','Organizza la lettura in rami e schemi. Ogni elemento torna alla fonte.')
        self.maps_panel=MindMapPanel(page,wiki22_root=WIKI22_DIR,on_topic=self.record_research,on_navigate=self.navigate_topic)
        self.maps_panel.pack(fill='both',expand=True,padx=36,pady=(0,22))
        for target,panel in [('Study',self.study_panel),('Articles',self.articles_panel),('Maps',self.maps_panel)]:
            bar=ttk.Frame(panel)
            bar.pack(fill='x',before=panel.scope,pady=(0,8))
            label=ttk.Label(bar,text='Una ricerca, più modi di studiare')
            label.pack(side='left',fill='x',expand=True)
            button=ttk.Button(bar,text='Riprendi argomento',command=lambda t=target:self.resume_journey(t,force=True))
            button.pack(side='right')
            panel.journey_label=label
            panel.journey_button=button

    def resume_journey(self,target,force=False):
        panel={'Study':self.study_panel,'Articles':self.articles_panel,'Maps':self.maps_panel}[target]
        ctx=self.journey.current
        if not ctx:return
        panel.journey_label.configure(text='Ricerca in corso: '+ctx.topic)
        action=self.journey.action(target,panel.topic.get(),panel.scope.current_ids or [],panel.busy)
        if action=='busy':return
        if action=='draft' and not force:
            panel.journey_label.configure(text='Ricerca: '+ctx.topic+' · il testo che stai scrivendo è conservato')
            return
        if action=='open' or force:
            try:
                if panel.open_topic(ctx.topic,list(ctx.scope)):
                    self.journey.acknowledge(target,ctx.topic,ctx.scope)
            except Exception as exc:panel.status.set('Ricerca non ripresa: '+str(exc))


    def _append_topic_links(self,topics,ids):
        if not topics:return
        self.chat_output.configure(state='normal')
        self.chat_output.insert('end','Approfondisci in Enciclopedia: ','meta')
        for topic in topics[:8]:
            tag='topic_'+str(len(self.chat_output.tag_names()))
            self.chat_output.insert('end',topic,tag);self.chat_output.insert('end','  ')
            self.chat_output.tag_configure(tag,foreground=BLUE,underline=True)
            self.chat_output.tag_bind(tag,'<Button-1>',lambda e,t=topic,s=list(ids):self.navigate_topic('Articles',t,s))
            self.chat_output.tag_bind(tag,'<Enter>',lambda e:self.chat_output.configure(cursor='hand2'))
            self.chat_output.tag_bind(tag,'<Leave>',lambda e:self.chat_output.configure(cursor='xterm'))
        self.chat_output.insert('end','\n\n');self.chat_output.configure(state='disabled')

    def _build_history(self):
        from wiki22.workspace_ui import HistoryPanel
        page=self._make_page('History','Le tue ricerche','Riprendi un argomento in Chat, Studio, Enciclopedia o Mappe.')
        self.history_panel=HistoryPanel(page,workspace=self.workspace,on_navigate=self.navigate_topic)
        self.history_panel.pack(fill='both',expand=True,padx=36,pady=(0,22))

    def record_research(self,query,topic,ids,kind):
        self.workspace.record(query,topic,ids,kind)
        origin={'Studio':'Study','Enciclopedia':'Articles','Mappe':'Maps','Chat':'Chat'}.get(kind)
        if origin:
            panel={'Study':getattr(self,'study_panel',None),'Articles':getattr(self,'articles_panel',None),'Maps':getattr(self,'maps_panel',None)}.get(origin)
            if panel:self.journey.acknowledge(origin,panel.topic.get(),ids)
        # Late results from a hidden view must not hijack a newer research.
        current=self.journey.current
        if origin==self.current_page or (kind=='Chat' and current and current.query==query):
            self.journey.activate(topic,ids,query)
        if kind in {'Studio','Enciclopedia'}:self.learning_coordinator.submit(topic,ids)

    def open_current(self,target):
        topic=self.topic_choice.get()
        if not topic or not getattr(self,'chat_topic_scope',None):
            self.chat_status.configure(text='Fai prima una ricerca, oppure apri Ricerche recenti.',bg=ORANGE_BG,fg=ORANGE);return
        self.navigate_topic(target,topic,self.chat_topic_scope)

    def navigate_topic(self,target,topic,ids,query=None):
        from wiki22.workspace_state import restore_scope
        try:
            if target=='Chat':
                if getattr(self,'query_busy',False):raise ValueError('Attendi il termine della domanda in corso.')
                restore_scope(self.scope_selector,ids)
                self.query_box.delete('1.0','end');self.query_box.insert('1.0',query or 'Parlami di '+topic)
                self.show_page('Chat');self.query_box.focus_set();return
            panel={'Study':self.study_panel,'Articles':self.articles_panel,'Maps':self.maps_panel}[target]
            if panel.busy:raise ValueError('Attendi il termine della lettura in corso.')
            if panel.open_topic(topic,ids):
                self.journey.activate(topic,ids,query or topic)
                self.journey.acknowledge(target,topic,ids)
                self.show_page(target)
        except Exception as exc:
            from tkinter import messagebox
            messagebox.showinfo('Ricerca non aperta',str(exc),parent=self)

    def apply_configuration(self,prefs):
        panel=getattr(self,'study_panel',None)
        if panel:
            for text in (panel.text,panel.guide_text,panel.feedback):text.configure(font=('DejaVu Sans',prefs['reading_font']))
        panel=getattr(self,'articles_panel',None)
        if panel:panel.text.configure(font=('DejaVu Sans',prefs['reading_font']))

    def _build_study(self):
        from wiki22.study_ui import StudyPanel
        page=self._make_page('Study','Studio','Leggi, collega le idee, conserva appunti e ripassa dalle fonti.')
        self.study_panel=StudyPanel(page,wiki22_root=WIKI22_DIR,on_topic=self.record_research,on_navigate=self.navigate_topic)
        self.study_panel.pack(fill='both',expand=True,padx=36,pady=(0,22))

    def _build_learning(self):
        from wiki22.learning_ui import LearningPanel
        page = self._make_page('Learning', 'Capacità e memoria',
                               'Vocabolario e regole misurabili, limiti dichiarati e letture registrate.')
        self.learning_panel = LearningPanel(page, product_root=WIKI22_DIR)
        self.learning_panel.pack(fill='both', expand=True, padx=36, pady=(0, 22))

    def _build_self_status(self):
        from wiki22.self_status_ui import SelfStatusPanel
        page = self._make_page('State', 'Wiki22 / Stato',
                               'Verifica cosa funziona e consulta le prove locali.')
        self.self_status_panel = SelfStatusPanel(page, product_root=WIKI22_DIR)
        self.self_status_panel.pack(fill='both', expand=True, padx=36, pady=(0, 22))

    def _build_settings(self) -> None:
        from wiki22.workspace_ui import ConfigurationPanel
        page=self._make_page('Settings','Impostazioni','Configura la lettura, i controlli e la cronologia di Wiki22.')
        tabs=ttk.Notebook(page);tabs.pack(fill='both',expand=True,padx=36,pady=(0,22))
        self.configuration_panel=ConfigurationPanel(tabs,workspace=self.workspace,on_save=self.apply_configuration)
        tabs.add(self.configuration_panel,text='Configurazione')
        diagnostics=ttk.Frame(tabs);tabs.add(diagnostics,text='Diagnostica')
        for label,var in [('Motore AI22',self.status_engine),('Rete',self.status_network),('Offline',self.status_offline),('Esecuzione',self.status_mode)]:
            row=ttk.Frame(diagnostics);row.pack(fill='x',pady=4)
            ttk.Label(row,text=label,width=20).pack(side='left');ttk.Label(row,textvariable=var).pack(side='left')
        self.diagnostic_output=tk.Text(diagnostics,wrap='word',font=('DejaVu Sans Mono',9),state='disabled')
        self.diagnostic_output.pack(fill='both',expand=True,pady=12)

    def _set_diagnostics(self, value: str) -> None:
        self.diagnostic_output.configure(state="normal")
        self.diagnostic_output.delete("1.0", "end")
        self.diagnostic_output.insert("1.0", value)
        self.diagnostic_output.configure(state="disabled")

    def _health_worker(self) -> None:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(WIKI22_DIR / "src")

        try:
            result = subprocess.run(
                ["bash", str(HEALTH_RUNNER)],
                text=True,
                capture_output=True,
                cwd=str(ROOT),
                env=env,
                timeout=120,
                check=False,
            )

            raw = result.stdout

            if result.stderr:
                raw += "\n" + result.stderr

            self.events.put(
                ("health", result.returncode, raw)
            )

        except Exception as exc:
            self.events.put(
                ("health_error", repr(exc))
            )

    def _warmup_worker(self):
        try:self.events.put(('memory_ready',self.query_client.warmup()))
        except Exception as exc:self.events.put(('memory_error',str(exc)))

    def _poll_events_impl(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] in {'memory_ready','memory_error'}:
                    self.memory_ready=True
                    self.ask_button.configure(state='normal')
                    if event[0]=='memory_ready':
                        self.memory_startup=event[1]
                        self.chat_status.configure(text='Pronto · memoria locale aperta',bg=GREEN_BG,fg=GREEN)
                    else:
                        self.memory_startup_error=event[1]
                        self.chat_status.configure(text='Memoria non disponibile: le richieste che la usano potrebbero fallire.',bg=ORANGE_BG,fg=ORANGE)
                    continue
                if event[0] == "query":
                    _, code, raw = event

                    self.query_busy = False
                    self.last_raw_result = raw
                    self.query_state = "TIMEOUT" if code == 124 else ("ERROR" if code else "SUCCESS")
                    cleaned = clean_terminal_output(raw)
                    answer = parse_user_answer(
                        cleaned,
                        getattr(
                            self,
                            "last_query",
                            "",
                        ),
                    )

                    if code:
                        answer = ("Il tempo disponibile per la domanda è scaduto. Puoi riprovare."
                                  if code == 124 else "Errore durante la domanda locale. I dettagli sono nelle impostazioni.")
                    structured_answer = _json_section(cleaned, "ANSWER")
                    insufficient = (isinstance(structured_answer, dict) and structured_answer.get("status") not in {"ANSWERED", "READING", "CLARIFY"}) or answer.startswith(("Non ho ancora abbastanza conoscenza locale", "Non riesco a ricavare una risposta verificata"))

                    if insufficient or code:
                        source_records = []
                        if insufficient and not code:
                            self.query_state = "INSUFFICIENT_KNOWLEDGE"
                    else:
                        source_records = extract_source_records(
                            cleaned
                        )

                    source_records = attribute_source_records(
                        source_records,
                        wiki22_root=WIKI22_DIR,
                        scope_env=getattr(
                            self,
                            "last_scope_env",
                            {},
                        ),
                    )

                    navigation=structured_answer.get('navigation',{}) if isinstance(structured_answer,dict) else {}
                    topics=navigation.get('topics',[])
                    topics=[t for t in topics if isinstance(t,str) and 0<len(t)<=180]
                    self.topic_combo.configure(values=topics)
                    self.topic_choice.set(topics[0] if topics else '')
                    self.chat_topic_scope=list(getattr(self,'last_scope_ids',[]))
                    self.record_research(self.last_query,topics[0] if topics else self.last_query,self.chat_topic_scope,'Chat')
                    if topics and not insufficient and code==0:self.learning_coordinator.submit(topics[0],self.chat_topic_scope)

                    sources = format_source_records(
                        source_records
                    )

                    source_count = len(
                        source_records
                    )

                    self._append_chat(
                        "assistant_label",
                        "WIKI22",
                    )

                    self._append_chat(
                        "text",
                        answer,
                    )
                    if not insufficient and not code:self._append_topic_links(topics,self.chat_topic_scope)

                    if isinstance(structured_answer,dict) and structured_answer.get('answer_type')=='LOCAL_SYSTEM_DESCRIPTION':
                        sources='Descrizione ricavata da metadati del pacchetto, identità dei componenti e conteggi dei lettori locali. Per i dettagli apri Wiki22 / Stato → Chi sono e tecnologie.'
                    self._set_sources(
                        sources
                        if sources
                        else (
                            "Nessuna fonte utilizzata per questa risposta."
                        )
                    )

                    self.ask_button.configure(
                        state="normal"
                    )

                    if code == 0:
                        if insufficient:
                            label = (
                                "Risposta non verificata · consulta Esplora"
                            )

                            self.chat_status.configure(
                                text=label,
                                bg=ORANGE_BG,
                                fg=ORANGE,
                            )

                        else:
                            label = (
                                ("Lettura dalla fonte · " if isinstance(structured_answer, dict) and structured_answer.get("status") == "READING" else "Chiarimento · " if isinstance(structured_answer, dict) and structured_answer.get("status") == "CLARIFY" else "Risposta locale pronta · ") +
                                f"{source_count} {'fonte' if source_count == 1 else 'fonti'}"
                            )

                            self.chat_status.configure(
                                text=label,
                                bg=GREEN_BG,
                                fg=GREEN,
                            )
                    else:
                        self.chat_status.configure(
                            text=("Tempo scaduto" if code == 124 else "Errore locale controllato"),
                            bg=ORANGE_BG,
                            fg=ORANGE,
                        )

                    # Every result retains the exact scope and raw diagnostics.
                    self._set_diagnostics(json.dumps(getattr(self, "last_scope_env", {})) + "\n" + cleaned)

                elif event[0] == "query_error":
                    _, error = event
                    self.query_busy = False
                    self.query_state = "ERROR"
                    self.ask_button.configure(state="normal")
                    self.chat_status.configure(text="Errore locale controllato", bg=ORANGE_BG, fg=ORANGE)
                    self._set_sources(format_source_records([]))
                    self._set_diagnostics(error)
                    self._append_chat("text", "Errore durante la domanda locale. Puoi riprovare.")

                elif event[0] == "health":
                    _, code, raw = event

                    cleaned = clean_terminal_output(raw)
                    upper = cleaned.upper()

                    self.status_engine.set(
                        "READY"
                        if code == 0 and "READY" in upper
                        else "CHECK"
                    )

                    self.status_network.set(
                        "BLOCKED"
                        if "BLOCKED" in upper
                        else "CHECK"
                    )

                    self.status_offline.set(
                        "PASS"
                        if "OFFLINE" in upper
                        else "CHECK"
                    )

                    self._set_diagnostics(
                        cleaned
                    )

                elif event[0] == "health_error":
                    _, error = event

                    self.status_engine.set(
                        "Non disponibile"
                    )

                    self._set_diagnostics(
                        error
                    )

        except queue.Empty:
            pass

        self.after(
            100,
            self._poll_events,
        )

    def _poll_events(self):
        """
        Fail-safe Tk event dispatcher.

        The implementation is allowed to raise, but the Desktop
        must never remain indefinitely in Thinking locally...
        and the Tk polling loop must survive.
        """
        try:
            return self._poll_events_impl()

        except Exception as exc:
            self.query_busy = False
            self.query_state = "ERROR"
            try:
                self._set_sources(format_source_records([]))
            except Exception:
                pass
            message = (
                f"Desktop event error: "
                f"{type(exc).__name__}: {exc}"
            )

            try:
                self.ask_button.configure(
                    state="normal"
                )
            except Exception:
                pass

            try:
                self.chat_status.configure(
                    text="Errore locale controllato",
                    bg=ORANGE_BG,
                    fg=ORANGE,
                )
            except Exception:
                pass

            try:
                self._set_diagnostics(
                    message
                )
            except Exception:
                pass

            # The original implementation schedules the next poll
            # on the normal path. If it raised before reaching that
            # point, schedule it here so the Desktop event loop lives.
            try:
                self.after(
                    100,
                    self._poll_events,
                )
            except Exception:
                pass

            return None


def main() -> int:
    app = Wiki22Desktop()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
