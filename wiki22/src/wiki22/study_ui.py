"""A local reading desk with source-linked notes and active recall."""
import queue
import threading
import tkinter as tk
from tkinter import ttk
from .scope_ui import ScopeSelector
from .knowledge.scope import resolve_scope,build_scope_provider
from .offline import OfflineGuard
from .study import StudyEngine,StudyNotebook

BG='#F4F7FB';INK='#172033';MUTED='#687386';BLUE='#2563EB'

class StudyPanel(tk.Frame):
    def __init__(self,master,*,wiki22_root,on_topic=None,on_navigate=None):
        super().__init__(master,bg=BG)
        self.configure_styles()
        self.on_topic=on_topic;self.on_navigate=on_navigate
        self.history=[];self.navigating_back=False
        self.root_path=wiki22_root;self.events=queue.Queue();self.busy=False;self.closed=False;self.lifecycle=threading.Lock()
        self.provider=None;self.book=None;self.lesson=None;self.choices=[];self.scope_ids=();self.card=0;self.revealed=False
        self.notebook=StudyNotebook(wiki22_root/'.runtime/study/notebook.sqlite3')
        self.scope=ScopeSelector(self,wiki22_root=wiki22_root);self.scope.pack(fill='x',pady=(0,10))
        self.scope.combo.bind('<<ComboboxSelected>>',lambda event:self.change_scope(),add='+')
        search=tk.Frame(self,bg=BG);search.pack(fill='x')
        self.topic=tk.StringVar()
        self.back_button=ttk.Button(search,text='← Torna',command=self.go_back,style='Study.TButton');self.back_button.pack(side='left',padx=(0,8));self.back_button.state(['disabled'])
        self.entry=ttk.Entry(search,style='Study.TEntry',textvariable=self.topic,font=('DejaVu Sans',12));self.entry.pack(side='left',fill='x',expand=True,ipady=7)
        self.entry.bind('<Return>',lambda e:self.search())
        self.search_button=ttk.Button(search,text='Apri un argomento',command=self.search,style='Study.Primary.TButton');self.search_button.pack(side='left',padx=(10,0),ipady=7)
        ttk.Button(search,text='Pagina enciclopedica',command=self.open_encyclopedia,style='Study.TButton').pack(side='left',padx=6)
        self.status=tk.StringVar(value='Cerca un argomento. Leggi un passaggio, scrivi cosa hai capito, poi confrontalo con la fonte.')
        tk.Label(self,textvariable=self.status,bg=BG,fg=MUTED,anchor='w',wraplength=940,font=('DejaVu Sans',9)).pack(fill='x',pady=10)
        body=tk.PanedWindow(self,orient='horizontal',bg=BG,sashwidth=10,bd=0);body.pack(fill='both',expand=True)
        left=tk.Frame(body,bg='white');body.add(left,width=210,minsize=170)
        tk.Label(left,text='ARGOMENTI',bg='white',fg=MUTED,anchor='w',font=('DejaVu Sans',9,'bold')).pack(fill='x',padx=12,pady=(14,8))
        self.results=tk.Listbox(left,bd=0,highlightthickness=0,exportselection=False,font=('DejaVu Sans',10),selectbackground='#EAF1FF',selectforeground=BLUE)
        self.results.pack(fill='both',expand=True,padx=8);self.results.bind('<<ListboxSelect>>',self.choose)
        tk.Label(left,text='Scegli una voce precisa.\nLe fonti restano locali.',bg='white',fg=MUTED,justify='left',font=('DejaVu Sans',9)).pack(anchor='w',padx=12,pady=12)
        right=tk.Frame(body,bg='white');body.add(right,minsize=420)
        self.tabs=ttk.Notebook(right,style='Study.TNotebook');self.tabs.pack(fill='both',expand=True)
        self.read_page=tk.Frame(self.tabs,bg='white');self.recall_page=tk.Frame(self.tabs,bg='white');self.note_page=tk.Frame(self.tabs,bg='white')
        self.guide_page=tk.Frame(self.tabs,bg='white');self.tabs.add(self.guide_page,text='  Comprendi  ')
        self.tabs.add(self.read_page,text='  Leggi  ');self.tabs.add(self.recall_page,text='  Ripassa  ');self.tabs.add(self.note_page,text='  Appunti  ')
        concepts=tk.Frame(self.read_page,bg='white');concepts.pack(fill='x',padx=22,pady=(10,0))
        self.concept=tk.StringVar()
        self.concept_choice=ttk.Combobox(concepts,textvariable=self.concept,state='readonly',width=35,style='Study.TCombobox')
        self.concept_choice.pack(side='left',fill='x',expand=True)
        ttk.Button(concepts,text='Apri concetto collegato →',command=self.open_concept,style='Study.TButton').pack(side='left',padx=(8,0))
        self.text=self.text_area(self.read_page)
        self.text.tag_configure('title',font=('DejaVu Sans',22,'bold'),spacing3=16)
        self.text.tag_configure('heading',font=('DejaVu Sans',12,'bold'),foreground=BLUE,spacing1=14)
        self.text.tag_configure('link',font=('DejaVu Sans',9),foreground=BLUE,underline=True)
        self.text.tag_configure('source',font=('DejaVu Sans',9),foreground=MUTED)
        self.render_text([('Il tuo spazio di studio','title'),('Trova una voce e segui tre passaggi: leggi, prova a spiegare senza guardare e confronta con la fonte.',''),('Gli appunti rimangono sul tuo dispositivo. Sono il tuo lavoro personale; non diventano automaticamente fatti della libreria.','source')])
        self.guide_text=self.text_area(self.guide_page)
        for tag in ('title','heading','source','link'):
            options={k:self.text.tag_cget(tag,k) for k in ('font','foreground','spacing1','spacing3','underline') if self.text.tag_cget(tag,k)}
            self.guide_text.tag_configure(tag,**options)
        self.render_text([('Dal testo alla comprensione','title'),('Apri un argomento: qui troverai le descrizioni riconosciute, i passaggi da confrontare e le domande su cui lavorare.','')],self.guide_text)
        practicebar=tk.Frame(self.recall_page,bg='white');practicebar.pack(fill='x',padx=22,pady=(12,0))
        tk.Label(practicebar,text='Esercizio',bg='white',fg=MUTED).pack(side='left',padx=(0,10))
        self.practice=tk.StringVar(value='Spiega')
        self.practice_choice=ttk.Combobox(practicebar,textvariable=self.practice,values=['Individua','Spiega','Valuta'],state='readonly',style='Study.TCombobox',width=18)
        self.practice_choice.pack(side='left');self.practice_choice.bind('<<ComboboxSelected>>',self.change_practice)
        self.prompt=tk.StringVar(value='Apri un argomento per iniziare il ripasso.')
        tk.Label(self.recall_page,textvariable=self.prompt,bg='white',fg=INK,justify='left',wraplength=680,font=('DejaVu Sans',14,'bold')).pack(fill='x',padx=22,pady=20)
        tk.Label(self.recall_page,text='Scrivi ciò che ricordi prima di rivedere il testo.',bg='white',fg=MUTED,anchor='w').pack(fill='x',padx=22)
        self.recall=tk.Text(self.recall_page,height=5,wrap='word',font=('DejaVu Sans',11),bd=1,relief='solid');self.recall.pack(fill='x',padx=22,pady=10)
        actions=tk.Frame(self.recall_page,bg='white');actions.pack(fill='x',padx=22)
        ttk.Button(actions,text='Confronta con la fonte',command=self.reveal,style='Study.Primary.TButton').pack(side='left')
        ttk.Button(actions,text='Passaggio successivo →',command=self.next_card,style='Study.TButton').pack(side='left',padx=10)
        self.feedback=self.text_area(self.recall_page)
        tk.Label(self.note_page,text='Il tuo quaderno',bg='white',fg=INK,font=('DejaVu Sans',16,'bold'),anchor='w').pack(fill='x',padx=22,pady=(20,10))
        self.note=tk.Text(self.note_page,height=6,wrap='word',font=('DejaVu Sans',11),bd=1,relief='solid');self.note.pack(fill='x',padx=22,pady=8)
        ttk.Button(self.note_page,text='Salva appunto con la fonte',command=self.save_note,style='Study.Primary.TButton').pack(anchor='w',padx=22,pady=8)
        self.saved=self.text_area(self.note_page)
        self.note.configure(state='disabled');self.recall.configure(state='disabled')
        from .language_study_ui import LanguageStudyPanel
        self.language_page=LanguageStudyPanel(self.tabs,validate_source=self.validate_language_source)
        self.tabs.add(self.language_page,text='  Lingua  ')
        self.after(70,self.poll)

    @staticmethod
    def configure_styles():
        style=ttk.Style()
        style.configure('Study.TButton',background='white',foreground=INK,borderwidth=1,padding=(12,8))
        style.map('Study.TButton',background=[('active','#EAF1FF')])
        style.configure('Study.Primary.TButton',background=BLUE,foreground='white',borderwidth=0,padding=(16,8))
        style.map('Study.Primary.TButton',background=[('disabled','#CAD8EF'),('active','#1D4ED8')])
        style.configure('Study.TEntry',fieldbackground='white',padding=6)
        style.configure('Study.TCombobox',fieldbackground='white',background='white',padding=5)
        style.map('Study.TCombobox',fieldbackground=[('readonly','white')],foreground=[('readonly',INK)])
        style.configure('Study.TNotebook',background='white',borderwidth=0)
        style.configure('Study.TNotebook.Tab',background='#EDF2FB',foreground=MUTED,padding=(16,10),borderwidth=0)
        style.map('Study.TNotebook.Tab',background=[('selected','white')],foreground=[('selected',BLUE)])

    @staticmethod
    def text_area(parent):
        frame=tk.Frame(parent,bg='white');frame.pack(fill='both',expand=True)
        bar=ttk.Scrollbar(frame);bar.pack(side='right',fill='y')
        text=tk.Text(frame,wrap='word',bd=0,highlightthickness=0,padx=22,pady=16,bg='white',fg=INK,font=('DejaVu Sans',11),spacing3=10,yscrollcommand=bar.set)
        text.pack(fill='both',expand=True);bar.configure(command=text.yview);text.configure(state='disabled');return text

    def render_text(self,blocks,target=None):
        target=target or self.text;target.configure(state='normal');target.delete('1.0','end')
        for text,tag in blocks:
            target.insert('end',text,tag);target.insert('end','\n',())
        target.configure(state='disabled');target.yview_moveto(0)

    def open_topic(self,topic,ids):
        from .workspace_state import restore_scope
        if self.busy:return False
        self.save_draft();restore_scope(self.scope,ids);self.topic.set(topic);self.search();return True

    def open_encyclopedia(self):
        if self.book and self.book.get('status')=='READY' and self.on_navigate:
            self.on_navigate('Articles',self.book['title'],list(self.scope_ids))

    def search(self):
        if self.busy:return
        topic=self.topic.get().strip()
        if not topic or len(topic)>180:self.status.set('Inserisci un argomento tra 1 e 180 caratteri.');return
        try:scope=resolve_scope(self.scope.registry,mode=self.scope.current_mode or 'SINGLE',requested_ids=self.scope.current_ids)
        except Exception as exc:self.status.set(str(exc));return
        self.save_draft()
        self.busy=True;self.search_button.state(['disabled']);self.scope.combo.configure(state='disabled');self.status.set('Apertura della voce e controllo delle fonti…')
        threading.Thread(target=self.worker,args=(topic,scope,None),daemon=True).start()

    def worker(self,topic,scope,article_id):
        provider=None
        try:
            with OfflineGuard():
                provider=build_scope_provider(self.root_path,scope);engine=StudyEngine(provider)
                choices=engine.find(topic)
                book=engine.open(article_id or choices[0]['article_id']) if article_id or len(choices)==1 else None
                from .study_lesson import build_lesson
                lesson=build_lesson(book,provider) if book and book.get('status')=='READY' else None
                with self.lifecycle:
                    if self.closed:provider.close()
                    else:self.events.put(('done',provider,choices,book,scope,lesson))
        except Exception as exc:
            if provider and hasattr(provider,'close'):provider.close()
            with self.lifecycle:
                if not self.closed:self.events.put(('error',str(exc)))

    def choose(self,event=None):
        if self.busy or not self.results.curselection():return
        item=self.choices[self.results.curselection()[0]]
        self.save_draft()
        self.busy=True;self.search_button.state(['disabled']);self.scope.combo.configure(state='disabled');self.status.set('Lettura delle fonti della voce…')
        threading.Thread(target=self.worker,args=(self.topic.get(),self.selected_scope,item['article_id']),daemon=True).start()

    def poll(self):
        try:
            while True:
                event=self.events.get_nowait();self.busy=False;self.search_button.state(['!disabled']);self.scope.combo.configure(state='readonly')
                if event[0]=='error':self.status.set('Lettura non completata: '+event[1]);continue
                self.save_draft()
                if self.provider and hasattr(self.provider,'close'):self.provider.close()
                _,self.provider,self.choices,self.book,self.selected_scope,self.lesson=event
                self.scope_ids=self.selected_scope.library_ids
                if self.book and self.book.get('status')=='READY':
                    item=(self.book['article_id'],self.book['title'])
                    if not self.history or self.history[-1]!=item:self.history.append(item);self.history=self.history[-32:]
                self.back_button.state(['!disabled'] if len(self.history)>1 else ['disabled'])
                self.results.delete(0,'end')
                for choice in self.choices:self.results.insert('end',choice['title'])
                if self.book:self.show_book()
                else:
                    self.clear_auxiliary()
                    self.status.set('Scegli una voce dall’elenco.' if self.choices else 'Nessun titolo trovato: prova una parola più breve o altre librerie.')
                    self.render_text([('Scegli l’argomento','title'),('Le voci disponibili sono elencate a sinistra.','')])
        except queue.Empty:pass
        if not self.closed:self.after(70,self.poll)

    def validate_language_source(self):
        if not self.book or self.book.get('status')!='READY' or self.provider is None:return False
        return StudyEngine(self.provider).open(self.book['article_id'])==self.book

    def show_book(self):
        book=self.book;self.card=0;self.tabs.select(self.guide_page)
        self.clear_auxiliary()
        if book['status']!='READY':
            self.render_text([('Lettura strutturata non disponibile','title'),('Questa voce non ha ancora passaggi leggibili verificati nell’indice di studio. Puoi consultare la fonte canonica in Esplora.','')]);self.status.set('Nessun passaggio di studio pubblicato per questa voce.');return
        self.note.configure(state='normal');self.recall.configure(state='normal')
        if self.on_topic:self.on_topic(self.topic.get(),book['title'],list(self.scope_ids),'Studio')
        from .workspace_state import WorkspaceState
        size=WorkspaceState(self.root_path).preferences()['reading_font']
        self.text.configure(font=('DejaVu Sans',size));self.guide_text.configure(font=('DejaVu Sans',size))
        self.concept_choice.configure(values=book.get('links',[]));self.concept.set('')
        blocks=[(book['title'],'title'),('Lettura selezionata dalla voce locale · '+str(len(book['paragraphs']))+' passaggi','source')]
        previous=None
        for i,p in enumerate(book['paragraphs'],1):
            if p['heading']!=previous:blocks.append((p['heading'],'heading'));previous=p['heading']
            blocks.append((p['text'],''));blocks.append((f'Mostra la fonte [{i}]',('link',f'source_{i-1}')))
        blocks.append(('Continua con un concetto collegato, oppure passa a Ripassa per provare a spiegare ciò che hai letto.','source'))
        self.render_text(blocks);self.status.set(f"{len(book['paragraphs'])} passaggi con provenienza · Offline · {book['title']}")
        for i in range(len(book['paragraphs'])):
            self.text.tag_bind(f'source_{i}','<Button-1>',lambda event,index=i:self.show_source(index))
            self.text.tag_bind(f'source_{i}','<Enter>',lambda event:self.text.configure(cursor='hand2'))
            self.text.tag_bind(f'source_{i}','<Leave>',lambda event:self.text.configure(cursor='xterm'))
        self.language_page.load_book(book)
        self.show_guide();self.prepare_card();self.show_notes()

    def show_guide(self):
        book=self.book;guide=book['guide'];blocks=[(book['title'],'title')]
        if book.get('profile'):
            blocks.extend([('Quadro iniziale · scheda locale','heading'),(book['profile']['text'],''),(book['profile']['revision_url'],'source')])
        if guide['conflicts']:
            blocks.append(('Le descrizioni disponibili non sono concordi. Confronta i passaggi prima di concludere.','heading'))
        if self.lesson and self.lesson['cards']:
            blocks.append(('Parti da qui','heading'))
            first=self.lesson['cards'][0]
            blocks.append((first['text'],''));blocks.append((f"Verifica il passaggio [{first['paragraph']+1}]",('link',f"guide_source_{first['paragraph']}")))
            if self.lesson['glossary']:
                blocks.append(('Termini da capire','heading'))
                for j,term in enumerate(self.lesson['glossary']):
                    blocks.append((term['title'],'heading'));blocks.append((term['text'],''))
                    blocks.append(('Apri la voce e la sua fonte →',('link',f'glossary_{j}')))
            example=next((c for c in self.lesson['cards'] if c['kind']=='example'),None)
            if example:
                blocks.append(('Un esempio dalla fonte','heading'));blocks.append((example['text'],''))
                blocks.append((f"Verifica il passaggio [{example['paragraph']+1}]",('link',f"guide_source_{example['paragraph']}")))
        if guide['claims']:
            blocks.append(('Definizioni e descrizioni','heading'))
            for claim in guide['claims'][:3]:
                blocks.append((claim['text'],''));blocks.append((f"Verifica il passaggio [{claim['paragraph']+1}]",('link',f"guide_source_{claim['paragraph']}")))
        else:blocks.append(('Non è stata ricostruita una definizione in questi passaggi. La lettura completa disponibile è nella scheda Leggi.','source'))
        selected={c['paragraph'] for c in guide['claims'][:3]}
        for kind,label in [('distinction','Distinzioni da capire'),('process','Processi descritti'),('cause','Cause e conseguenze nel testo')]:
            indices=[i for i in guide['passages'][kind] if i not in selected][:1]
            if not indices:continue
            blocks.append((label,'heading'))
            for i in indices:
                selected.add(i);blocks.append((book['paragraphs'][i]['text'],''));blocks.append((f'Leggi la fonte [{i+1}]',('link',f'guide_source_{i}')))
        blocks.extend([('Verifica ciò che hai capito','heading'),('1. Come definiresti l’argomento?\n2. Quali condizioni o eccezioni devi conservare?\n3. Che cosa non è ancora spiegato da questi passaggi?',''),('Passa a Ripassa: scegli Individua, Spiega o Valuta. Le risposte restano nel tuo quaderno.','source')])
        self.render_text(blocks,self.guide_text)
        if self.lesson:
            selected.update(c['paragraph'] for c in self.lesson['cards'])
            for j,term in enumerate(self.lesson['glossary']):
                self.guide_text.tag_bind(f'glossary_{j}','<Button-1>',lambda event,title=term['title']:self.open_lesson_term(title))
        for i in selected:self.guide_text.tag_bind(f'guide_source_{i}','<Button-1>',lambda event,index=i:self.show_source(index))

    def open_lesson_term(self,title):
        if self.busy:return
        self.topic.set(title);self.search()

    def change_practice(self,event=None):
        if not self.book or self.book.get('status')!='READY':return
        answer=self.recall.get('1.0','end').strip()
        if answer:self.notebook.save(self.scope_ids,self.book,'Ripasso\n'+answer)
        self.prepare_card();self.show_notes()

    def show_source(self,index):
        if not self.book or self.book.get('status')!='READY':return
        try:fresh=StudyEngine(self.provider).open(self.book['article_id'])
        except Exception as exc:self.status.set('Fonte non verificabile: '+str(exc));return
        if fresh!=self.book:self.status.set('Fonte cambiata: riapri la voce.');return
        p=fresh['paragraphs'][index]
        window=tk.Toplevel(self);window.title('Fonte · '+fresh['title']);window.geometry('760x500');window.configure(bg='white')
        tk.Label(window,text=fresh['title'],font=('DejaVu Sans',18,'bold'),bg='white',fg=INK,anchor='w').pack(fill='x',padx=22,pady=(20,8))
        target=self.text_area(window)
        self.render_text([(p['text'],''),('Wikipedia italiana · '+p['heading'],''),
            ('Questo passaggio è stato ricontrollato sulla copia locale.',''),(fresh['original_revision_url'],'')],target)
        ttk.Button(window,text='Torna alla lettura',command=window.destroy,style='Study.TButton').pack(anchor='e',padx=22,pady=12)
        self.source_window=window

    def go_back(self):
        if self.busy or len(self.history)<2:return
        self.save_draft();self.history.pop();aid,title=self.history[-1];self.topic.set(title)
        self.busy=True;self.search_button.state(['disabled']);self.scope.combo.configure(state='disabled')
        self.status.set('Riapertura della voce precedente…')
        threading.Thread(target=self.worker,args=(title,self.selected_scope,aid),daemon=True).start()

    def clear_auxiliary(self):
        if hasattr(self,'language_page'):self.language_page.load_book(None)
        self.concept_choice.configure(values=[]);self.concept.set('')
        for widget in (self.recall,self.note):
            widget.configure(state='normal');widget.delete('1.0','end');widget.configure(state='disabled')
        self.render_text([],self.feedback);self.render_text([],self.saved);self.render_text([],self.guide_text)
        self.prompt.set('Apri un argomento per iniziare il ripasso.')
        self.revealed=False

    def change_scope(self):
        if self.busy:return
        self.save_draft();self.book=None;self.choices=[];self.results.delete(0,'end');self.clear_auxiliary();self.history=[];self.back_button.state(['disabled'])
        self.concept_choice.configure(values=[]);self.concept.set('')
        if self.provider and hasattr(self.provider,'close'):self.provider.close()
        self.provider=None
        self.render_text([('Conoscenza cambiata','title'),('Cerca nuovamente l’argomento nelle librerie selezionate.','')])
        self.render_text([],self.saved);self.render_text([],self.feedback)
        self.prompt.set('Apri un argomento per iniziare il ripasso.')
        self.status.set('La lettura precedente è chiusa. Gli appunti restano nel quaderno della loro voce.')

    def open_concept(self):
        if self.busy or not self.concept.get():return
        self.topic.set(self.concept.get());self.search()

    def prepare_card(self):
        if not self.book or self.book['status']!='READY':return
        p=self.book['paragraphs'][self.card]
        from .study_guide import practice_prompt
        self.prompt.set(f"{self.card+1}/{len(self.book['paragraphs'])} · {self.book['title']} · {p['heading']}\n"+practice_prompt(self.practice.get(),p))
        self.recall.delete('1.0','end');self.render_text([('Prova prima a ricordare. Poi confronta concetti, condizioni ed eventuali eccezioni con il testo.','')],self.feedback)
        self.revealed=False

    def reveal(self):
        if not self.book or self.book['status']!='READY':return
        try:fresh=StudyEngine(self.provider).open(self.book['article_id'])
        except Exception as exc:self.status.set('Fonte non verificabile: '+str(exc));return
        if fresh!=self.book:self.status.set('Fonte cambiata: riapri la voce.');return
        p=self.book['paragraphs'][self.card]
        self.render_text([(p['text'],''),('Controlla: hai conservato il concetto principale, le condizioni e le eccezioni? Quale passaggio sostiene la tua spiegazione?',''),(self.book['original_revision_url'],'')],self.feedback)
        self.revealed=True

    def next_card(self):
        if not self.book or self.book['status']!='READY':return
        answer=self.recall.get('1.0','end').strip()
        if answer:self.notebook.save(self.scope_ids,self.book,f"Ripasso · {self.book['paragraphs'][self.card]['heading']}\n{answer}")
        self.card=(self.card+1)%len(self.book['paragraphs']);self.prepare_card();self.show_notes()

    def save_draft(self):
        if self.book and self.book.get('status')=='READY':
            body=self.note.get('1.0','end').strip()
            if body:self.notebook.save(self.scope_ids,self.book,body);self.note.delete('1.0','end')
            recall=self.recall.get('1.0','end').strip()
            if recall:self.notebook.save(self.scope_ids,self.book,'Ripasso\n'+recall);self.recall.delete('1.0','end')

    def save_note(self):
        if not self.book or self.book['status']!='READY':self.status.set('Apri prima una voce.');return
        try:self.notebook.save(self.scope_ids,self.book,self.note.get('1.0','end'))
        except ValueError as exc:self.status.set(str(exc));return
        self.note.delete('1.0','end');self.show_notes();self.status.set('Appunto salvato sul dispositivo con il riferimento alla voce.')

    def show_notes(self):
        notes=self.notebook.list(self.scope_ids,self.book['article_id'])
        self.render_text([(n['body']+'\nRevisione della fonte: '+n['revision'],'') for n in notes] or [('Nessun appunto per questa voce.','')],self.saved)

    def destroy(self):
        with self.lifecycle:
            self.closed=True
            while True:
                try:event=self.events.get_nowait()
                except queue.Empty:break
                if event[0]=='done' and event[1] is not self.provider:event[1].close()
        self.save_draft();self.notebook.close()
        if self.provider and hasattr(self.provider,'close'):self.provider.close()
        super().destroy()
