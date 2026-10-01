"""Local Atlas and source-bound article experiences for the desktop."""
from __future__ import annotations
import queue
import threading
import tkinter as tk
from tkinter import ttk

from .scope_ui import ScopeSelector
from .knowledge.scope import resolve_scope, build_scope_provider
from .knowledge.atlas import Atlas, browse_titles, canonical_record, identity
from .articles import ArticleComposer
from .ai22_adapter import AI22Adapter
from .native22_linguistic_guarded.session import NativeSession
from .offline import OfflineGuard

RELATION_LABELS={'definition_of':'definizione','capitale_di':'capitale di','autore_di':'autore di',
    'situato_in':'si trova','nato_a':'nascita a','parte_di':'parte di','membro_di':'membro di',
    'president_of':'presidenza di'}

def node_label(node):
    if node.get('type')=='PROPOSIZIONE':
        prop=node.get('observations',[{}])[0].get('proposition',{})
        if prop:
            relation=RELATION_LABELS.get(prop['predicate'],prop['predicate'].replace('property_of:','ruolo: '))
            return f"{prop['subject']} → {relation} → {prop['object']}"
    if node.get('type')=='RELAZIONE':
        return RELATION_LABELS.get(node['label'],node['label'].replace('property_of:','ruolo: '))
    return node.get('label',node.get('title',''))

VIEWS = {'Alfabetico':None,'Categorie':'CATEGORIA','Temi':'TEMA','Entità':'ENTITÀ',
         'Relazioni':'RELAZIONE','Tempo':'TEMPO','Fonti':'FONTE','Proposizioni':'PROPOSIZIONE'}
BLUE='#2563EB'; NAVY='#172033'; MUTED='#687386'; BG='#F4F7FB'


class ResearchPanel(tk.Frame):
    def __init__(self, master, *, wiki22_root, mode='atlas',on_topic=None):
        super().__init__(master,bg=BG)
        self.root_path=wiki22_root;self.on_topic=on_topic
        self.mode=mode
        self.events=queue.Queue()
        self.busy=False;self.closed=False;self.provider=None;self.atlas=None;self.result=None
        self.items=[];self.letters=[];self.after_key=''
        self.scope=ScopeSelector(self,wiki22_root=wiki22_root)
        self.scope.pack(fill='x',pady=(0,14))
        bar=tk.Frame(self,bg=BG);bar.pack(fill='x')
        self.topic=tk.StringVar()
        self.entry=ttk.Entry(bar,textvariable=self.topic,font=('DejaVu Sans',12))
        self.entry.pack(side='left',fill='x',expand=True,ipady=8)
        self.entry.bind('<Return>',lambda event:self.run())
        self.run_button=ttk.Button(bar,text='Componi articolo' if mode=='articles' else 'Esplora',command=self.run)
        self.run_button.pack(side='left',padx=(10,0),ipady=8)
        self.status=tk.StringVar(value='Scegli le librerie e un argomento. Tutto avviene sul computer.')
        tk.Label(self,textvariable=self.status,bg=BG,fg=MUTED,anchor='w',wraplength=860,
                 font=('DejaVu Sans',9)).pack(fill='x',pady=(10,12))
        body=tk.PanedWindow(self,orient='horizontal',bg=BG,sashwidth=10,bd=0)
        body.pack(fill='both',expand=True)
        left=tk.Frame(body,bg='white',width=240)
        body.add(left,minsize=200,width=240)
        self.view=tk.StringVar(value='Entità')
        if mode=='atlas':
            combo=ttk.Combobox(left,textvariable=self.view,values=list(VIEWS),state='readonly')
            combo.pack(fill='x',padx=12,pady=12)
            combo.bind('<<ComboboxSelected>>',lambda event:self.show_view())
        else:
            tk.Label(left,text='FONTI DELL’ARTICOLO',bg='white',fg=MUTED,
                     font=('DejaVu Sans',9,'bold'),anchor='w').pack(fill='x',padx=12,pady=16)
        self.listbox=tk.Listbox(left,bd=0,highlightthickness=0,exportselection=False,
            bg='white',fg=NAVY,selectbackground='#EAF1FF',selectforeground=BLUE,
            font=('DejaVu Sans',10),activestyle='none')
        self.listbox.pack(fill='both',expand=True,padx=10)
        self.listbox.bind('<<ListboxSelect>>',lambda event:self.select())
        self.more_button=ttk.Button(left,text='Titoli successivi →',command=self.more_titles)
        if mode=='atlas':self.more_button.pack(fill='x',padx=12,pady=12)
        if mode=='articles':ttk.Button(left,text='Torna all’articolo',command=self.show_article).pack(fill='x',padx=12,pady=12)
        right=tk.Frame(body,bg='white');body.add(right,minsize=400)
        scrollbar=ttk.Scrollbar(right);scrollbar.pack(side='right',fill='y')
        self.text=tk.Text(right,wrap='word',bd=0,highlightthickness=0,bg='white',fg=NAVY,
            padx=24,pady=20,font=('DejaVu Sans',11),spacing3=9,yscrollcommand=scrollbar.set)
        self.text.pack(fill='both',expand=True);scrollbar.configure(command=self.text.yview)
        self.text.tag_configure('title',font=('DejaVu Sans',20,'bold'),spacing3=18)
        self.text.tag_configure('heading',font=('DejaVu Sans',12,'bold'),foreground=BLUE,spacing1=14)
        self.text.tag_configure('note',font=('DejaVu Sans',9),foreground=MUTED)
        self.write([('Dalla conoscenza alle connessioni' if mode=='atlas' else 'Un articolo, con le sue prove','title'),
            ('Cerca un argomento per consultare documenti, relazioni e riferimenti temporali.' if mode=='atlas' else
             'Wiki22 compone una sintesi in italiano dalle fonti locali. Ogni affermazione rimanda al passaggio che la sostiene.',''),
            ('Le relazioni di Esplora sono osservazioni ricavate dai documenti. Articoli verifica le proposizioni e segnala evidenze insufficienti o contraddittorie.','note')])
        self.after(100,self.poll)

    def write(self,blocks):
        self.text.configure(state='normal');self.text.delete('1.0','end')
        for text,tag in blocks:
            self.text.insert('end',text,tag)
            self.text.insert('end','\n',())
        self.text.configure(state='disabled');self.text.yview_moveto(0)

    def run(self):
        if self.busy:return
        topic=self.topic.get().strip()
        alphabetic = self.mode=='atlas' and self.view.get()=='Alfabetico'
        if (not topic and not alphabetic) or len(topic)>240:
            self.status.set('Inserisci un argomento tra 1 e 240 caratteri.');return
        try:
            scope=resolve_scope(self.scope.registry,mode=self.scope.current_mode or 'SINGLE',requested_ids=self.scope.current_ids)
        except Exception as exc:
            self.status.set(str(exc));return
        self.busy=True;self.run_button.state(['disabled']);self.entry.state(['disabled'])
        self.status.set('Lettura delle fonti locali e verifica in corso…')
        threading.Thread(target=self.worker,args=(topic,scope),daemon=True).start()

    def worker(self,topic,scope):
        provider=None;atlas=None;composer=None;native=None
        try:
            with OfflineGuard():
                provider=build_scope_provider(self.root_path,scope)
                if self.mode=='atlas':
                    atlas=Atlas(provider,self.root_path/'.runtime/memidx/observations.sqlite3')
                    metrics=atlas.search(topic) if topic else {'evidence_examined':0}
                    atlas.close()  # SQLite remains owned by this worker.
                    letters=browse_titles(provider,topic,limit=30)
                    result=dict(metrics=metrics,letters=letters,topic=topic,scope=scope.library_ids)
                else:
                    native=NativeSession(self.root_path/'.runtime/native22/memory.sqlite3')
                    adapter=AI22Adapter(workspace_root=self.root_path.parent,wiki22_root=self.root_path)
                    composer=ArticleComposer(provider,adapter,native_session=native,
                        cache_path=self.root_path/'.runtime/memidx/observations.sqlite3')
                    result=composer.compose(topic);result['scope']=scope.library_ids
                    composer.close();composer=None;native.close();native=None
                if self.closed:
                    if hasattr(provider,'close'):provider.close()
                else:self.events.put(('done',provider,atlas,result))
        except Exception as exc:
            if atlas:atlas.close()
            if composer:composer.close()
            if native:native.close()
            if provider and hasattr(provider,'close'):provider.close()
            self.events.put(('error',str(exc)))

    def poll(self):
        try:
            while True:
                event=self.events.get_nowait()
                self.busy=False;self.run_button.state(['!disabled']);self.entry.state(['!disabled'])
                if event[0]=='error':
                    self.status.set('Ricerca non completata: '+event[1]);continue
                if self.provider and hasattr(self.provider,'close'):self.provider.close()
                _,self.provider,self.atlas,self.result=event
                if self.mode=='atlas':
                    self.letters=self.result['letters'];self.after_key=''
                    n=self.result['metrics']['evidence_examined']
                    self.status.set(f'{n} evidenze esaminate · Indice derivato della ricerca · Librerie: '+', '.join(self.result['scope']))
                    self.show_view()
                    if self.on_topic and self.result['topic']:self.on_topic(self.result['topic'],self.result['topic'],list(self.result['scope']),'Esplora')
                else:self.show_article()
        except queue.Empty:pass
        if not self.closed:self.after(100,self.poll)

    def show_view(self):
        if not self.atlas:return
        kind=VIEWS[self.view.get()]
        self.items=self.atlas.nodes(kind) if kind else self.letters
        self.listbox.delete(0,'end')
        for node in self.items:self.listbox.insert('end',node_label(node))
        self.more_button.state(['!disabled' if kind is None else 'disabled'])
        self.write([(self.view.get(),'title'),
                    (f'{len(self.items)} elementi nella vista corrente. Selezionane uno per aprire le fonti.',''),
                    ('Questa mappa descrive le evidenze consultate, non tutte le relazioni presenti nella libreria.','note')])

    def more_titles(self):
        if self.busy or not self.provider or self.view.get()!='Alfabetico' or not self.letters:return
        self.after_key=self.letters[-1]['cursor']
        self.letters=browse_titles(self.provider,self.result['topic'],after=self.after_key,limit=30)
        self.show_view()

    def select(self):
        if self.busy or not self.listbox.curselection():return
        index=self.listbox.curselection()[0]
        try:
            if self.mode=='articles':
                claim=self.result['claims'][index];source=claim['source']
                row=canonical_record(self.provider,source['evidence_id'])
                if identity(row)!=source['source_binding']:raise ValueError('Fonte cambiata: ricomponi l’articolo')
                self.write([(f'Fonte {source["number"]} · {source["article_title"]}','title'),
                    (claim['text'],''),(source['excerpt'],''),(source.get('original_revision_url',source['source']),'note'),
                    ('Passaggio riletto dalla libreria locale.','note')]);return
            node=self.items[index]
            if self.view.get()=='Alfabetico':
                self.topic.set(node['title']);self.run();return
            rows=self.atlas.resolve(node['id'])
            links=self.atlas.connections(node['id'])
            blocks=[(node_label(node),'title'),('Osservazione ricavata dalle fonti; apri i passaggi per valutarne il contesto.','note')]
            if links:
                blocks.extend([('Collegamenti','heading'),('\n'.join(dict.fromkeys(node_label(x['node']) for x in links)),'')])
            for row in rows[:8]:
                blocks.extend([(row['title']+' · '+row['section_title'],'heading'),(row['text'],''),(row['source_ref'],'note')])
            self.write(blocks)
        except Exception as exc:self.status.set('Verifica non riuscita: '+str(exc))

    def show_article(self):
        if not self.result:return
        result=self.result
        self.listbox.delete(0,'end')
        for claim in result['claims']:
            self.listbox.insert('end',f'[{claim["number"]}] '+claim['source']['article_title'])
        if result['status']!='READY':
            message='Le fonti esaminate si contraddicono. Non posso comporre un articolo affidabile.' if result['status']=='CONFLICT' else 'Non ho trovato abbastanza proposizioni verificabili per comporre questo articolo.'
            self.write([(result['title'],'title'),(message,''),('Prova un titolo preciso, consulta Esplora o scegli altre librerie.','note')])
            self.status.set('Nessuna sintesi pubblicata · '+', '.join(result['scope']));return
        blocks=[(result['title'],'title'),(result['scope_note'],'note')]
        for section in result['sections']:
            blocks.append((section['title'],'heading'));blocks.extend((p,'') for p in section['paragraphs'])
        if result['conflicting_propositions']:
            blocks.append(('Alcune proposizioni in conflitto sono state escluse dalla sintesi.','note'))
        blocks.append(('Seleziona un riferimento a sinistra per rileggere la fonte.','note'))
        self.write(blocks)
        self.status.set(f'{len(result["claims"])} affermazioni con fonte · Offline · Librerie: '+', '.join(result['scope']))

    def destroy(self):
        self.closed=True
        if self.provider and hasattr(self.provider,'close'):self.provider.close()
        super().destroy()
