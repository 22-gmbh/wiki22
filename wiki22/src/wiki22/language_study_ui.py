"""Asynchronous linguistic study panel; no learning or personal-memory writes."""
import hashlib
import queue
import threading
import tkinter as tk
from tkinter import ttk
from .language_study import MODES, analyze_passage

BG = 'white'; INK = '#172033'; MUTED = '#687386'; BLUE = '#2563EB'


class LanguageStudyPanel(tk.Frame):
    def __init__(self, master, *, validate_source=None):
        super().__init__(master, bg=BG)
        self.validate_source = validate_source
        self.passages = []
        self.source_text = None
        self.source_name = ''
        self.generation = 0
        self.busy = False
        self.closed = False
        self.events = queue.Queue()
        self.token_rows = {}
        self.last_result = None
        navigation = tk.Frame(self, bg=BG)
        navigation.pack(fill='x', padx=12, pady=5)
        ttk.Button(navigation, text='Testo e domanda', command=lambda: self.viewport.yview_moveto(0), style='Study.TButton').pack(side='left')
        ttk.Button(navigation, text='Risultati', command=lambda: self.viewport.yview_moveto(1), style='Study.TButton').pack(side='left', padx=8)
        self.analysis_notice = tk.Label(navigation, text='Analisi automatica\nNon verifica i fatti', bg=BG, fg=MUTED, font=('DejaVu Sans', 9), justify='right')
        self.analysis_notice.pack(side='right', padx=4)
        area = tk.Frame(self, bg=BG)
        area.pack(fill='both', expand=True)
        self.viewport = tk.Canvas(area, bg=BG, highlightthickness=0)
        scrollbar = ttk.Scrollbar(area, orient='vertical', command=self.viewport.yview)
        self.viewport.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right', fill='y')
        self.viewport.pack(side='left', fill='both', expand=True)
        body = tk.Frame(self.viewport, bg=BG)
        self.body = body
        self.body_window = self.viewport.create_window((0, 0), window=body, anchor='nw')
        body.bind('<Configure>', lambda event: self.viewport.configure(scrollregion=self.viewport.bbox('all')))
        self.viewport.bind('<Configure>', self.resize_viewport)
        self.title = tk.StringVar(value='Esplora la lingua di un passaggio')
        tk.Label(body, textvariable=self.title, bg=BG, fg=INK, font=('DejaVu Sans', 15, 'bold'), anchor='w').pack(fill='x', padx=20, pady=(16, 4))
        tk.Label(body, text='Analisi automatica locale, senza LLM. Può contenere errori: confrontala con il testo.',
                 bg=BG, fg=MUTED, anchor='w', wraplength=780).pack(fill='x', padx=20, pady=(0, 10))
        source_bar = tk.Frame(body, bg=BG); source_bar.pack(fill='x', padx=20)
        self.passage_choice = ttk.Combobox(source_bar, state='disabled', style='Study.TCombobox')
        self.passage_choice.pack(side='left', fill='x', expand=True)
        self.passage_choice.bind('<<ComboboxSelected>>', self.choose_passage)
        ttk.Button(source_bar, text='Testo libero', command=self.free_text, style='Study.TButton').pack(side='left', padx=(8, 0))
        self.source_label = tk.StringVar(value='Testo personale: non viene aggiunto alla libreria.')
        tk.Label(body, textvariable=self.source_label, bg=BG, fg=MUTED, anchor='w', wraplength=780).pack(fill='x', padx=20, pady=5)
        self.input = tk.Text(body, height=5, wrap='word', font=('DejaVu Sans', 11), relief='solid', bd=1, padx=8, pady=8)
        self.input.pack(fill='x', padx=20)
        self.input.tag_configure('selected_word', background='#DBEAFE')
        self.input.bind('<<Modified>>', self.edited)
        actions = tk.Frame(body, bg=BG); actions.pack(fill='x', padx=20, pady=10)
        self.mode = tk.StringVar(value=MODES[0]); self.word = tk.StringVar()
        self.mode_choice = ttk.Combobox(actions, textvariable=self.mode, values=MODES, state='readonly', width=18, style='Study.TCombobox')
        self.mode_choice.pack(side='left')
        tk.Label(actions, text='Parola', bg=BG, fg=MUTED).pack(side='left', padx=(8, 0))
        self.word_entry = ttk.Entry(actions, textvariable=self.word, width=12, style='Study.TEntry')
        self.word_entry.pack(side='left', padx=8)
        self.word_entry.bind('<Return>', lambda event: self.start())
        self.run_button = ttk.Button(actions, text='Analizza', command=self.start, style='Study.Primary.TButton')
        self.run_button.pack(side='left')
        tk.Label(body, text='Per lemma, categoria o caratteristiche, indica la parola. Puoi anche sceglierla dalla tabella.',
                 bg=BG, fg=MUTED, anchor='w', wraplength=780).pack(fill='x', padx=20)
        self.question = tk.StringVar()
        qbar = tk.Frame(body, bg=BG); qbar.pack(fill='x', padx=20, pady=(8, 5))
        tk.Label(qbar, text='Domanda libera sulla lingua', bg=BG, fg=MUTED).pack(side='left', padx=(0, 8))
        self.question_entry = ttk.Entry(qbar, textvariable=self.question, style='Study.TEntry')
        self.question_entry.pack(side='left', fill='x', expand=True)
        self.question_entry.bind('<Return>', lambda event: self.start())
        self.status = tk.StringVar(value='Apri una voce in Studio o incolla un testo. L’analisi resta separata dai tuoi appunti.')
        tk.Label(body, textvariable=self.status, bg=BG, fg=BLUE, anchor='w', wraplength=780).pack(fill='x', padx=20, pady=8)
        table_frame = tk.Frame(body, bg=BG); table_frame.pack(fill='both', expand=True, padx=20)
        self.table = ttk.Treeview(table_frame, columns=('word', 'lemma', 'category', 'features'), show='headings', height=7)
        for key, label, width in [('word', 'Parola', 140), ('lemma', 'Lemma', 140), ('category', 'Categoria', 160), ('features', 'Caratteristiche', 330)]:
            self.table.heading(key, text=label); self.table.column(key, width=width, minwidth=60, stretch=True)
        bar = ttk.Scrollbar(table_frame, orient='vertical', command=self.table.yview)
        horizontal = ttk.Scrollbar(table_frame, orient='horizontal', command=self.table.xview)
        self.table.configure(yscrollcommand=bar.set, xscrollcommand=horizontal.set)
        table_frame.rowconfigure(0, weight=1); table_frame.columnconfigure(0, weight=1)
        self.table.grid(row=0, column=0, sticky='nsew'); bar.grid(row=0, column=1, sticky='ns'); horizontal.grid(row=1, column=0, sticky='ew')
        self.table.bind('<<TreeviewSelect>>', self.select_word)
        self.answer = tk.Text(body, height=4, wrap='word', bg='#F4F7FB', fg=INK, font=('DejaVu Sans', 11), bd=0, padx=12, pady=8, state='disabled')
        self.answer.pack(fill='x', padx=20, pady=(8, 15))
        self.timer = self.after(60, self.poll)

    def resize_viewport(self, event):
        self.viewport.itemconfigure(self.body_window, width=event.width)
        if hasattr(self, 'table'):
            self.table.configure(height=max(3, min(7, (event.height - 165) // 22)))
        for child in self.body.winfo_children():
            if isinstance(child, tk.Label):
                child.configure(wraplength=max(200, event.width - 40))

    def clear_result(self):
        self.last_result = None; self.token_rows.clear()
        self.table.delete(*self.table.get_children())
        self.answer.configure(state='normal'); self.answer.delete('1.0', 'end'); self.answer.configure(state='disabled')
        self.input.tag_remove('selected_word', '1.0', 'end')

    def edited(self, event=None):
        if not self.input.edit_modified():
            return
        self.input.edit_modified(False)
        self.generation += 1
        self.clear_result()
        text = self.input.get('1.0', 'end-1c')
        if self.source_text is not None and text == self.source_text:
            self.source_label.set(self.source_name)
        else:
            self.source_label.set('Testo personale o modificato: analisi sulla tua bozza, non sulla fonte originale.')

    def load_book(self, book):
        self.viewport.yview_moveto(0)
        self.generation += 1; self.clear_result(); self.word.set(''); self.question.set('')
        if not book or book.get('status') != 'READY':
            self.passages = []; self.passage_choice.configure(values=[], state='disabled'); self.passage_choice.set('Nessuna voce aperta')
            self.title.set('Esplora la lingua di un passaggio'); self.source_text = None; self.source_name = ''
            self.input.delete('1.0', 'end'); self.status.set('Apri una voce o scrivi un testo da analizzare.'); return
        self.title.set('La lingua di «' + book['title'] + '»')
        self.passages = [dict(text=p['text'], label=f"{i+1}. {p['heading']} · {p['text'][:60]}",
                              source=f"Fonte locale: {book['title']} · {p['heading']}") for i, p in enumerate(book['paragraphs'])]
        self.passage_choice.configure(values=[p['label'] for p in self.passages], state='readonly' if self.passages else 'disabled')
        if self.passages:
            self.passage_choice.current(0); self.choose_passage()

    def choose_passage(self, event=None):
        i = self.passage_choice.current()
        if not 0 <= i < len(self.passages):
            return
        self.viewport.yview_moveto(0)
        p = self.passages[i]; self.source_text = p['text']; self.source_name = p['source']
        self.input.delete('1.0', 'end'); self.input.insert('1.0', p['text'])
        self.source_label.set(p['source']); self.generation += 1; self.clear_result()
        self.word.set(''); self.question.set(''); self.status.set('Passaggio pronto. Scegli l’analisi o fai una domanda sulla lingua.')

    def free_text(self):
        self.viewport.yview_moveto(0)
        self.source_text = None; self.source_name = ''; self.input.delete('1.0', 'end')
        self.source_label.set('Testo personale: non viene aggiunto alla libreria.'); self.input.focus_set()
        self.generation += 1; self.clear_result()

    def start(self):
        if self.busy or self.closed:
            return
        # Process any pending text edit before binding the job to this generation.
        if self.input.edit_modified():
            self.edited()
        text = self.input.get('1.0', 'end-1c')
        if text == self.source_text and self.validate_source:
            try:
                if not self.validate_source():
                    self.clear_result(); self.status.set('La fonte è cambiata: riapri la voce prima di analizzarla.'); return
            except Exception:
                self.clear_result(); self.status.set('La fonte non è verificabile: riapri la voce.'); return
        self.busy = True; self.run_button.state(['disabled']); self.mode_choice.configure(state='disabled'); self.word_entry.configure(state='disabled'); self.question_entry.configure(state='disabled'); self.clear_result(); self.status.set('Analisi locale in corso…')
        generation = self.generation
        args = (text, self.mode.get(), self.word.get(), self.question.get())
        threading.Thread(target=self.worker, args=(generation, args), daemon=True).start()

    def worker(self, generation, args):
        try:
            payload = analyze_passage(*args); error = None
        except ValueError as exc:
            payload = None; error = str(exc)
        except (OSError, ImportError):
            payload = None; error = 'Il componente linguistico non è disponibile in questa installazione.'
        except Exception:
            payload = None; error = 'Analisi non disponibile. Il testo e gli appunti sono conservati.'
        self.events.put((generation, payload, error))

    def poll(self):
        try:
            while True:
                generation, payload, error = self.events.get_nowait()
                self.busy = False; self.run_button.state(['!disabled']); self.mode_choice.configure(state='readonly'); self.word_entry.configure(state='normal'); self.question_entry.configure(state='normal')
                if generation != self.generation:
                    self.status.set('Il testo è cambiato: avvia una nuova analisi.'); continue
                if error:
                    self.status.set(error); continue
                if hashlib.sha256(self.input.get('1.0', 'end-1c').encode()).hexdigest() != payload['input_sha256']:
                    self.status.set('Il testo è cambiato: avvia una nuova analisi.'); continue
                self.render(payload)
        except queue.Empty:
            pass
        if not self.closed:
            self.timer = self.after(60, self.poll)

    def render(self, payload):
        self.last_result = payload; result = payload['result']; rows = result.get('PROVA', {}).get('analyses', [])
        for i, row in enumerate(rows):
            key = str(i); self.token_rows[key] = row
            features = ', '.join(f'{k}: {v}' for k, v in row['morphology'].items())
            self.table.insert('', 'end', iid=key, values=(row['form'], row['lemma'], row['category'], features))
        self.answer.configure(state='normal'); self.answer.delete('1.0', 'end'); self.answer.insert('end', result['RISPOSTA']); self.answer.configure(state='disabled')
        if result['STATO'] == 'ANALISI_LINGUISTICA':
            self.status.set(f"{len(rows)} elementi analizzati · {payload['elapsed_ms']:.0f} ms")
        else:
            self.status.set('Richiesta non risolta. Prova Analisi completa o indica una parola presente una sola volta.')

        self.update_idletasks()
        self.viewport.yview_moveto(1)

    def select_word(self, event=None):
        if not self.table.selection() or self.last_result is None:
            return
        row = self.token_rows[self.table.selection()[0]]; self.word.set(row['form'])
        detail = f"{row['form']} — {row['category']}; lemma: {row['lemma']}\n" + ', '.join(f'{k}: {v}' for k, v in row['morphology'].items())
        self.answer.configure(state='normal'); self.answer.delete('1.0', 'end'); self.answer.insert('end', detail); self.answer.configure(state='disabled')
        result = self.last_result['result']; request = result['PROVA']['request']
        self.input.tag_remove('selected_word', '1.0', 'end')
        # A question may quote a different passage; only highlight context-bound spans.
        if request['passage_origin'] == 'context':
            a, b = row['span']; self.input.tag_add('selected_word', f'1.0+{a}c', f'1.0+{b}c'); self.input.see(f'1.0+{a}c')

    def destroy(self):
        self.closed = True
        if self.timer:
            self.after_cancel(self.timer)
        super().destroy()
