"""Local encyclopedic reading, paginated paper reading with source-bound citations."""
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog
from .scope_ui import ScopeSelector
from .knowledge.scope import resolve_scope,build_scope_provider
from .offline import OfflineGuard
from .encyclopedia import compose_reading
from .study import StudyEngine
from .research_document import verify_document, export_html
from .workspace_state import WorkspaceState,restore_scope

class EncyclopediaPanel(tk.Frame):
    def __init__(self,master,*,wiki22_root,on_topic=None,on_navigate=None):
        super().__init__(master,bg='#F4F7FB')
        self.root_path=wiki22_root;self.on_topic=on_topic;self.on_navigate=on_navigate
        self.workspace=WorkspaceState(wiki22_root);self.events=queue.Queue();self.busy=False;self.closed=False
        self.provider=None;self.result=None;self.choices=[];self.page=0;self.lifecycle=threading.Lock()
        self.scope=ScopeSelector(self,wiki22_root=wiki22_root);self.scope.pack(fill='x')
        bar=ttk.Frame(self);bar.pack(fill='x',pady=10)
        self.topic=tk.StringVar();self.entry=ttk.Entry(bar,textvariable=self.topic,font=('DejaVu Sans',12))
        self.entry.pack(side='left',fill='x',expand=True);self.entry.bind('<Return>',lambda e:self.run())
        self.button=ttk.Button(bar,text='Apri pagina enciclopedica',command=self.run);self.button.pack(side='left',padx=8)
        self.page_limit=tk.StringVar(value=str(self.workspace.preferences()['article_pages']))
        ttk.Label(bar,text='Pagine').pack(side='left')
        self.page_selector=ttk.Combobox(bar,textvariable=self.page_limit,values=list(range(1,13)),width=3,state='readonly')
        self.page_selector.pack(side='left',padx=4)
        self.status=tk.StringVar(value='Cerca una voce oppure aprila dalla Chat o dalle Ricerche.')
        ttk.Label(self,textvariable=self.status,wraplength=850).pack(anchor='w',pady=4)
        self.chooser=ttk.Combobox(self,state='readonly');self.chooser.bind('<<ComboboxSelected>>',self.choose)
        body=tk.Frame(self,bg='#DCDDD5');body.pack(fill='both',expand=True,pady=8)
        self.body=body
        self.paper_canvas=tk.Canvas(body,bg='#DCDDD5',highlightthickness=0)
        outer_scroll=ttk.Scrollbar(body,command=self.paper_canvas.yview)
        outer_scroll.pack(side='right',fill='y');self.paper_canvas.pack(fill='both',expand=True)
        self.paper_canvas.configure(yscrollcommand=outer_scroll.set)
        self.paper=tk.Frame(self.paper_canvas,bg='#FFFEF8',padx=38,pady=32,width=794,height=1123)
        self.paper.pack_propagate(False)
        self.paper_window=self.paper_canvas.create_window(16,20,window=self.paper,anchor='nw',width=794,height=1123)
        self.paper_canvas.bind('<Configure>',self.layout_paper)
        for event,delta in [('<Button-4>',-3),('<Button-5>',3)]:
            self.paper_canvas.bind(event,lambda e,d=delta:self.paper_canvas.yview_scroll(d,'units'))
        self.paper_canvas.bind('<MouseWheel>',lambda e:self.paper_canvas.yview_scroll(-1 if e.delta>0 else 1,'units'))
        tk.Label(self.paper,text='W I K I 2 2   /   R I C E R C A   E N C I C L O P E D I C A',bg='#FFFEF8',fg='#4C6656',font=('DejaVu Sans',9)).pack(anchor='w')
        self.headline=tk.Label(self.paper,text='La tua enciclopedia locale',bg='#FFFEF8',fg='#203A2C',font=('DejaVu Serif',24,'bold'),anchor='w',justify='left',wraplength=900)
        self.headline.pack(fill='x',pady=(8,4))
        self.paper_note=tk.Label(self.paper,text='Apri una voce. Ogni numero rimanda alla fonte locale.',bg='#FFFEF8',fg='#536357',font=('DejaVu Sans',9),anchor='w',justify='left',wraplength=900)
        self.paper_note.pack(fill='x',pady=(0,12))
        self.columns=tk.Frame(self.paper,bg='#FFFEF8');self.columns.pack(fill='both',expand=True)
        self.column_frames=[];self.texts=[]
        for i in range(2):
            frame=tk.Frame(self.columns,bg='#FFFEF8');frame.grid(row=0,column=i,sticky='nsew',padx=(0,14) if i==0 else (14,0))
            scroll=ttk.Scrollbar(frame)
            text=tk.Text(frame,wrap='word',width=30,padx=5,pady=8,bg='#FFFEF8',fg='#24332A',relief='flat',spacing3=8,yscrollcommand=scroll.set)
            text.pack(fill='both',expand=True);scroll.configure(command=text.yview)
            text.tag_configure('title',font=('DejaVu Serif',23,'bold'))
            text.tag_configure('heading',font=('DejaVu Serif',14,'bold'),foreground='#203A2C',spacing1=12)
            text.tag_configure('note',font=('DejaVu Sans',9),foreground='#5B6F60')
            text.tag_configure('link',foreground='#17694F',underline=True,offset=4,font=('DejaVu Sans',9,'bold'))
            self.column_frames.append(frame);self.texts.append(text)
        self.text=self.texts[0] # Public documentary output retained for integrations.
        self.columns.columnconfigure(0,weight=1,uniform='paper');self.columns.columnconfigure(1,weight=1,uniform='paper');self.columns.rowconfigure(0,weight=1)
        self.narrow=None;self.columns.bind('<Configure>',self.resize_paper)
        footer=ttk.Frame(self);self.footer=footer;footer.pack(side='bottom',fill='x',before=body,pady=(4,0))
        self.previous=ttk.Button(footer,text='← Precedente',command=lambda:self.turn(-1));self.previous.grid(row=0,column=0,sticky='w')
        self.counter=tk.StringVar();self.counter_label=ttk.Label(footer,textvariable=self.counter);self.counter_label.grid(row=0,column=1,padx=12)
        self.next=ttk.Button(footer,text='Successiva →',command=lambda:self.turn(1));self.next.grid(row=0,column=2,sticky='w')
        self.study_button=ttk.Button(footer,text='Studia questo argomento',command=lambda:self.navigate('Study'));self.study_button.grid(row=0,column=4,sticky='e')
        self.export_button=ttk.Button(footer,text='Salva pagina…',command=self.export);self.export_button.grid(row=0,column=3,sticky='e',padx=8);self.footer.columnconfigure(3,weight=1)
        self.export_button.state(['disabled'])
        self.write([('La tua enciclopedia locale','title'),('Apri una voce per leggere fino a dodici pagine con fonti numerate. Scegli la lunghezza qui sopra. Le voci brevi conservano la loro lunghezza.','')])
        self.previous.state(['disabled']);self.next.state(['disabled']);self.study_button.state(['disabled'])
        self.after(80,self.poll)
    def layout_paper(self,event=None):
        width=max(320,min(794,self.paper_canvas.winfo_width()-32))
        height=max(1123,round(width*297/210))
        self.paper_canvas.itemconfigure(self.paper_window,width=width)
        self.paper_canvas.coords(self.paper_window,max(16,(self.paper_canvas.winfo_width()-width)//2),20)
        self.update_idletasks()
        sizes=[]
        for text in self.texts:
            count=text.count('1.0','end','update','ypixels')
            lines=(count[0] if isinstance(count,tuple) else count) or 1
            from tkinter import font
            sizes.append(lines+50)
        content=(sum(sizes) if self.narrow else max(sizes))+230
        height=max(height,content)
        self.paper_canvas.itemconfigure(self.paper_window,height=height)
        self.paper_canvas.configure(scrollregion=(0,0,width+32,height+40))

    def resize_paper(self,event):
        narrow=event.width<640
        self.headline.configure(wraplength=max(220,event.width));self.paper_note.configure(wraplength=max(220,event.width))
        if narrow==self.narrow:return
        self.narrow=narrow
        for i,frame in enumerate(self.column_frames):frame.grid(row=i if narrow else 0,column=0 if narrow else i,sticky='nsew',padx=0 if narrow else ((0,14) if i==0 else (14,0)))
        self.columns.columnconfigure(0,weight=1,uniform='' if narrow else 'paper')
        self.columns.columnconfigure(1,weight=0 if narrow else 1,uniform='' if narrow else 'paper',minsize=0)
        self.export_button.grid(row=1 if narrow else 0,column=0 if narrow else 3,sticky='w' if narrow else 'e',pady=(8,0) if narrow else 0)
        self.study_button.grid(row=1 if narrow else 0,column=2 if narrow else 4,sticky='e',pady=(8,0) if narrow else 0)
        self.columns.rowconfigure(1,weight=1 if narrow else 0)
    def write(self,blocks):
        for text in self.texts:
            text.configure(state='normal',font=('DejaVu Serif',self.workspace.preferences()['reading_font']))
            text.delete('1.0','end')
        for value,tag in blocks:self.text.insert('end',value+'\n\n',tag)
        for text in self.texts:text.configure(state='disabled');text.yview_moveto(0)
    def open_topic(self,topic,ids):
        if self.busy:return False
        restore_scope(self.scope,ids);self.topic.set(topic);self.run();return True
    def run(self,article_id=None):
        if self.busy:return
        topic=self.topic.get().strip()
        if not topic or len(topic)>180:self.status.set('Scrivi un argomento tra 1 e 180 caratteri.');return
        try:scope=resolve_scope(self.scope.registry,mode=self.scope.current_mode or 'SINGLE',requested_ids=self.scope.current_ids)
        except Exception as exc:self.status.set(str(exc));return
        prefs=self.workspace.preferences();page_limit=int(self.page_limit.get());self.busy=True;self.button.state(['disabled']);self.entry.state(['disabled']);self.scope.combo.state(['disabled']);self.chooser.state(['disabled'])
        self.status.set('Apertura della voce e verifica delle fonti…')
        def worker():
            provider=None
            try:
                with OfflineGuard():
                    provider=build_scope_provider(self.root_path,scope)
                    result=compose_reading(provider,topic,pages=page_limit,verification=prefs['verification'],article_id=article_id)
                with self.lifecycle:
                    if self.closed:provider.close()
                    else:self.events.put(('ok',provider,result,scope))
            except Exception as exc:
                if provider:provider.close()
                with self.lifecycle:
                    if not self.closed:self.events.put(('error',str(exc)))
        threading.Thread(target=worker,daemon=True).start()
    def choose(self,event=None):
        i=self.chooser.current()
        if 0<=i<len(self.choices):self.run(self.choices[i]['article_id'])
    def poll(self):
        try:
            while True:
                event=self.events.get_nowait();self.busy=False
                self.button.state(['!disabled']);self.entry.state(['!disabled']);self.scope.combo.configure(state='readonly');self.chooser.configure(state='readonly')
                if self.provider:self.provider.close();self.provider=None
                self.result=None;self.export_button.state(['disabled']);self.study_button.state(['disabled']);self.previous.state(['disabled']);self.next.state(['disabled'])
                if event[0]=='error':
                    self.write([('Lettura non disponibile','title'),('La verifica non è stata completata. Riprova ad aprire la voce.','')]);self.status.set(event[1]);continue
                _,self.provider,self.result,self.selected_scope=event
                r=self.result;self.choices=r['choices'];self.chooser.configure(values=[c['title'] for c in self.choices])
                self.chooser.pack_forget()
                if r['status']=='READY':
                    self.page=0;self.show_page();self.study_button.state(['!disabled'])
                    if self.on_topic:self.on_topic(r['title'],r['title'],list(self.selected_scope.library_ids),getattr(self,'research_kind','Enciclopedia'))
                else:
                    message={'CHOOSE':'Scegli la voce precisa dall’elenco.','NOT_FOUND':'Nessun titolo trovato nelle librerie selezionate.','NO_READING':'La voce esiste, ma non ha passaggi di lettura verificati. Puoi consultarla in Esplora.'}[r['status']]
                    if r['status']=='CHOOSE':self.chooser.pack(fill='x',before=self.body,pady=5)
                    self.write([(r['title'],'title'),(message,'')]);self.status.set(message)
        except queue.Empty:pass
        if not self.closed:self.after(80,self.poll)
    def show_page(self):
        r=self.result;doc=r['document'];verify_document(doc,r['book'])
        self.headline.configure(text=r['title'])
        c=doc['counts']
        self.paper_note.configure(text=f"Proposizioni ricomposte: {c['COMPOSED']} · Letture strutturate: {c['STRUCTURED']} · Frasi documentarie: {c['EXCERPT']}. Clicca i numeri per leggere fonte e contesto.")
        for text,column in zip(self.texts,doc['pages'][self.page]):
            text.configure(state='normal',font=('DejaVu Serif',self.workspace.preferences()['reading_font']));text.delete('1.0','end')
            previous=None
            for block in column:
                heading=block['heading'] or 'Introduzione'
                if heading!=previous:text.insert('end',heading+(' · seguito' if block.get('continuation') else '')+'\n','heading');previous=heading
                if block['conflict']:text.insert('end','Disaccordo rilevato: passaggio conservato senza sintesi.\n','note')
                kind=None
                for s in block['sentences']:
                    if kind!=s['kind']:
                        if kind:text.insert('end','\n\n')
                        label={'COMPOSED':'SINTESI VERIFICATA','STRUCTURED':'LETTURA STRUTTURATA','EXCERPT':'PASSAGGIO DELLA FONTE'}[s['kind']]
                        text.insert('end',label+'\n','note');kind=s['kind']
                    text.insert('end',s['text']);tag=f"citation_{s['note']}"
                    text.insert('end',f" [{s['note']}]",('link',tag));text.insert('end',' ')
                    text.tag_bind(tag,'<Button-1>',lambda e,n=s['note']:self.citation(n))
                    text.tag_bind(tag,'<Enter>',lambda e,t=text:t.configure(cursor='hand2'))
                    text.tag_bind(tag,'<Leave>',lambda e,t=text:t.configure(cursor='xterm'))
                text.insert('end','\n\n')
            text.configure(state='disabled');text.yview_moveto(0)
        self.layout_paper();self.paper_canvas.yview_moveto(0)
        self.counter.set(f"Pagina {self.page+1} di {len(doc['pages'])}")
        self.previous.state(['!disabled'] if self.page else ['disabled'])
        self.next.state(['!disabled'] if self.page<len(doc['pages'])-1 else ['disabled'])
        self.export_button.state(['!disabled'])
        self.status.set(f"{len(doc['selected_paragraphs'])} di {doc['available_paragraphs']} passaggi locali indicizzati · {len(doc['notes'])} note · Offline · Wikipedia / CC BY-SA")
    def turn(self,delta):
        if self.result and self.result['status']=='READY':self.page=max(0,min(len(self.result['document']['pages'])-1,self.page+delta));self.show_page()
    def checked_book(self):
        from .extended_reading import open_extended
        current=open_extended(self.provider,self.result['book']['article_id'])
        if current!=self.result['book']:raise ValueError('Fonte cambiata: riapri la voce.')
        verify_document(self.result['document'],current)
        return current
    def citation(self,number):
        if self.busy:return
        try:
            self.checked_book();n=self.result['document']['notes'][number-1]
            import json
            content=f"[{number}] {n['title']} — {n['heading']}\n\nPASSAGGIO CHE SOSTIENE LA FRASE\n{n['excerpt']}\n\nCONTESTO COMPLETO\n{n['context']}\n\nWikipedia · CC BY-SA\n{n['revision_url']}\nVoce locale: {n['article_id']}\nPosizione nel paragrafo: {n['start']}–{n['end']}\n\nRiferimenti alla libreria\n"+json.dumps(n['spans'],ensure_ascii=False,indent=2)
            self.source_window(content,'Fonte ['+str(number)+'] · '+self.result['title'])
        except Exception as exc:self.status.set(str(exc))
    def source_window(self,content,title):
        window=tk.Toplevel(self);window.title(title);window.geometry('820x600')
        scroll=ttk.Scrollbar(window);scroll.pack(side='right',fill='y')
        text=tk.Text(window,wrap='word',padx=22,pady=20,font=('DejaVu Sans',11),yscrollcommand=scroll.set);text.pack(fill='both',expand=True);scroll.configure(command=text.yview)
        text.insert('end',content);text.configure(state='disabled')
    def source(self,index):
        if self.busy:return
        try:
            book=self.checked_book();p=book['paragraphs'][index] if index>=0 else dict(heading='Scheda locale',text=book['profile']['text'])
            self.source_window(book['title']+'\n'+p['heading']+'\n\n'+p['text']+'\n\nWikipedia · CC BY-SA\n'+book['original_revision_url'],'Fonte · '+book['title'])
        except Exception as exc:self.status.set(str(exc))
    def export(self):
        if self.busy or not self.result or self.result['status']!='READY':return
        try:
            book=self.checked_book();content=export_html(self.result['document'],book)
            filename=filedialog.asksaveasfilename(parent=self,title='Salva ricerca enciclopedica',defaultextension='.html',initialfile='Wiki22-ricerca.html',filetypes=[('Pagina stampabile','*.html')])
            if filename:
                from pathlib import Path
                Path(filename).write_text(content,encoding='utf-8');self.status.set('Pagina salvata con note e contesto. Aprila nel browser per leggerla o stamparla.')
        except Exception as exc:self.status.set(str(exc))
    def navigate(self,target):
        if self.result and self.result['status']=='READY' and self.on_navigate:self.on_navigate(target,self.result['title'],list(self.selected_scope.library_ids))
    def destroy(self):
        with self.lifecycle:
            self.closed=True
            while not self.events.empty():
                event=self.events.get_nowait()
                if event[0]=='ok':event[1].close()
        if self.provider:self.provider.close()
        super().destroy()
