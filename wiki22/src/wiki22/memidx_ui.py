"""Optional, bounded MEMIDX001 Atlas consumer. No changes to QA retrieval."""
from __future__ import annotations

import json
import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from wiki22.knowledge.memidx_candidate import (
    CanonicalLibrary, MemIndex, Federation, VERSION, file_hash,
)

VIEWS = {'Categorie':'CATEGORIA', 'Temi':'TEMA', 'Entità':'ENTITÀ',
         'Relazioni':'RELAZIONE', 'Tempo':'TEMPO', 'Fonti':'FONTE',
         'Proposizioni':'PROPOSIZIONE', 'Alfabetico':None}
MODES = {'Singola':'SINGLE', 'Unificata':'UNIFIED', 'Personalizzata':'CUSTOM'}


class CandidateAtlas:
    """A manifest binds each derived file to a separate canonical library."""

    def __init__(self, manifest_path, registry):
        self.registry = registry
        self.sources = {}
        self.indexes = {}
        self.pack_hashes = {}
        try:
            manifest = json.loads(Path(manifest_path).read_text())
            if manifest.get('program') != VERSION or manifest.get('exp001_status') != 'PASS':
                raise ValueError('Manifest sperimentale non validato')
            rows = manifest['libraries']
            if not 1 <= len(rows) <= 2:
                raise ValueError('Il candidato ammette al massimo due librerie controllate')
            for row in rows:
                ident = row['library_id']
                if ident in self.indexes:
                    raise ValueError('Identità di libreria duplicata')
                pack = registry.resolve_pack(ident)
                if pack is None or file_hash(pack) != row['registry_pack_sha256']:
                    raise ValueError('La libreria è cambiata: aggiornare il manifest derivato')
                index_path = Path(row['index_path'])
                if file_hash(index_path) != row['artifact_sha256']:
                    raise ValueError('Indice assente o modificato: rigenerare dai contenuti canonici')
                index = MemIndex.load(index_path)
                source = CanonicalLibrary(row['canonical_path'])
                self.sources[ident] = source
                if (index.library_id != ident or source.library_id != ident or
                    index.source_sha != source.sha256 or source.sha256 != row['source_sha256'] or
                    index.identity != row['build_id']):
                    raise ValueError('Indice e fonte canonica non corrispondono')
                self.indexes[ident] = index
                self.pack_hashes[ident] = row['registry_pack_sha256']
            self.federation = Federation(list(self.indexes.values()))
        except Exception:
            self.close()
            raise

    def available(self):
        return [row for row in self.registry.list_libraries() if row.get('enabled')]

    def scope(self, mode, ids):
        active = {row['id'] for row in self.available()}
        selected = sorted(active) if mode == 'UNIFIED' else list(dict.fromkeys(ids))
        if mode not in {'SINGLE', 'UNIFIED', 'CUSTOM'} or not selected or (mode == 'SINGLE' and len(selected) != 1) or not set(selected) <= active:
            raise ValueError('Selezionare le librerie attive per questo ambito')
        missing = set(selected) - self.indexes.keys()
        if missing:
            # Never silently narrow a federated or custom selection.
            raise ValueError('Indice non disponibile per: ' + ', '.join(sorted(missing)))
        for ident in selected:
            self.check_pack(ident)
        return self.federation.scope(mode, selected) if mode != 'UNIFIED' else [self.indexes[x] for x in selected]

    def check_pack(self, ident):
        pack = self.registry.resolve_pack(ident)
        if pack is None or file_hash(pack) != self.pack_hashes[ident]:
            raise ValueError('Libreria modificata: aggiornare gli indici e ricaricare')

    def evidence(self, node_id):
        for ident, index in self.indexes.items():
            if node_id in index.nodes:
                row = self.registry.get(ident)
                if not row or not row.get('enabled'):
                    raise ValueError('Libreria non attiva')
                self.check_pack(ident)
                return index.evidence_for_node(node_id, self.sources[ident])
        raise KeyError(node_id)

    def close(self):
        for source in self.sources.values():
            source.close()
        self.sources.clear()


class ExploreWindow(tk.Toplevel):
    def __init__(self, master, registry, selected_id=None):
        super().__init__(master)
        self.title('Wiki22 — Esplora le librerie')
        self.geometry('1080x760')
        self.registry = registry
        self.atlas = None
        self.nodes = {}
        self.mode = tk.StringVar(value='Singola')
        self.view = tk.StringVar(value='Categorie')
        self.status = tk.StringVar()
        ttk.Label(self, text='Esplora · Candidato sperimentale', font=('', 18, 'bold')).pack(anchor='w', padx=16, pady=(12, 4))
        ttk.Label(self, text='Seleziona una libreria. Per un ambito personalizzato, selezionane più di una.').pack(anchor='w', padx=16)
        controls = ttk.Frame(self)
        controls.pack(fill='x', padx=16, pady=8)
        self.mode_combo = ttk.Combobox(controls, textvariable=self.mode, values=list(MODES), state='readonly', width=18)
        self.mode_combo.pack(side='left')
        self.mode_combo.bind('<<ComboboxSelected>>', lambda _: self.refresh())
        self.view_combo = ttk.Combobox(controls, textvariable=self.view, values=list(VIEWS), state='readonly', width=20)
        self.view_combo.pack(side='left', padx=8)
        self.view_combo.bind('<<ComboboxSelected>>', lambda _: self.refresh())
        self.reload_btn = ttk.Button(controls, text='Ricarica indici', command=self.reload)
        self.reload_btn.pack(side='right')
        self.libraries = tk.Listbox(self, selectmode='extended', exportselection=False, height=3)
        self.libraries.pack(fill='x', padx=16)
        self.library_ids = []
        for row in registry.list_libraries():
            if row.get('enabled'):
                self.library_ids.append(row['id'])
                self.libraries.insert('end', row['name'])
        if selected_id in self.library_ids:
            self.libraries.selection_set(self.library_ids.index(selected_id))
        elif self.library_ids:
            self.libraries.selection_set(0)
        self.libraries.bind('<<ListboxSelect>>', lambda _: self.refresh())
        panes = ttk.Panedwindow(self, orient='vertical')
        panes.pack(fill='both', expand=True, padx=16, pady=8)
        upper = ttk.Frame(panes)
        self.tree = ttk.Treeview(upper, columns=('kind', 'library'), selectmode='browse')
        self.tree.heading('#0', text='Voce / sottocategoria')
        self.tree.heading('kind', text='Tipo')
        self.tree.heading('library', text='Libreria')
        self.tree.column('#0', width=580)
        self.tree.column('kind', width=130)
        self.tree.column('library', width=220)
        scroll = ttk.Scrollbar(upper, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', lambda _: self.resolve())
        panes.add(upper, weight=2)
        lower = ttk.Frame(panes)
        ttk.Label(lower, text='Articolo · evidenza · fonte canonica').pack(anchor='w')
        self.details = tk.Text(lower, wrap='word', height=12, state='disabled')
        details_scroll = ttk.Scrollbar(lower, command=self.details.yview)
        self.details.configure(yscrollcommand=details_scroll.set)
        details_scroll.pack(side='right', fill='y')
        self.details.pack(fill='both', expand=True)
        panes.add(lower, weight=1)
        ttk.Label(self, textvariable=self.status, wraplength=1020).pack(anchor='w', padx=16, pady=(0, 10))
        self.protocol('WM_DELETE_WINDOW', self.destroy)
        self.reload()

    def write_details(self, text):
        self.details.configure(state='normal')
        self.details.delete('1.0', 'end')
        self.details.insert('1.0', text)
        self.details.configure(state='disabled')

    def reload(self):
        if self.atlas:
            self.atlas.close()
            self.atlas = None
        try:
            self.atlas = CandidateAtlas(os.environ.get('WIKI22_MEMIDX_CANDIDATE_MANIFEST', ''), self.registry)
            self.refresh()
        except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
            self.tree.delete(*self.tree.get_children())
            self.nodes.clear()
            self.write_details('')
            self.status.set('Esplorazione non disponibile: ' + str(error))

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        self.nodes.clear()
        self.write_details('')
        if not self.atlas:
            return
        try:
            ids = [self.library_ids[i] for i in self.libraries.curselection()]
            indexes = self.atlas.scope(MODES[self.mode.get()], ids)
            kind = VIEWS[self.view.get()]
            for index in indexes:
                nodes = index.nodes_of(kind) if kind else sorted(index.nodes.values(), key=lambda n: (n['label'].casefold(), n['id']))
                for node in nodes:
                    self.nodes[node['id']] = (index, node)
                    self.tree.insert('', 'end', iid=node['id'], text=node['label'], values=(node['type'], index.name))
                if kind == 'CATEGORIA':
                    for parent, child, role, _ in sorted(index.edges):
                        if role == 'sottocategoria':
                            self.tree.move(child, parent, 'end')
                            self.tree.item(parent, open=True)
            self.status.set(f'{len(indexes)} librerie separate · {len(self.nodes)} voci · ogni voce rimanda alla fonte canonica')
        except (ValueError, KeyError) as error:
            self.status.set(str(error))

    def resolve(self):
        selected = self.tree.selection()
        if not selected or not self.atlas:
            return
        try:
            index, node = self.nodes[selected[0]]
            rows = self.atlas.evidence(selected[0])
            text = [node['label'], f"Libreria: {index.name} ({index.library_id})"]
            if node['type'] == 'ENTITÀ':
                text.append('Tipo: ' + index.entity_type(node['id']))
                related = index.related_entities(node['id'])
                text.append('Entità collegate (verificare le proposizioni): ' + ', '.join(n['label'] for n in related))
            # Always expose polarity, qualifiers and time, including relations.
            props = [node] if node['type'] == 'PROPOSIZIONE' else index.propositions_for_entity(node['id']) if node['type'] == 'ENTITÀ' else [index.nodes[b] for a,b,role,_ in index.edges if a == node['id'] and role == 'proposizione']
            for prop in {p['id']: p for p in props}.values():
                for observation in prop['observations']:
                    p = observation['proposition']
                    tense = {'current':'presente grammaticale', 'past':'passato', 'event':'evento', 'future':'futuro'}.get(p['tense'], p['tense'])
                    text.append(f"Proposizione: {p['subject']} → {p['predicate']} → {p['object']} | Negazione: {'sì' if p['polarity']=='negative' else 'no'} | Incertezza: {'no' if p['certain'] else 'sì'} | Qualificatori: {', '.join(p['modifiers']) or '—'} | Anni: {', '.join(p['years']) or '—'} | Tempo: {tense}")
            for row in rows:
                text.extend(['', 'Articolo: ' + row['title'], 'Fonte: ' + row['source_ref'],
                             'Sezione: ' + row['section_title'], 'MEM: ' + row['mem_record_id'],
                             'Evidenza: ' + row['evidence_id'], row['text']])
            self.write_details('\n'.join(text))
        except (OSError, ValueError, KeyError) as error:
            self.write_details('Evidenza non disponibile: ' + str(error))

    def destroy(self):
        if self.atlas:
            self.atlas.close()
            self.atlas = None
        super().destroy()
