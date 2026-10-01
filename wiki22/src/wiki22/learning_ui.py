"""Bounded local learning history and explicitly unverified human clarifications."""
import queue
import threading
import tkinter as tk
from tkinter import ttk
from .learning_status import snapshot, record_clarification


class LearningPanel(ttk.Frame):
    def __init__(self, master, *, product_root):
        super().__init__(master)
        self.product_root=product_root; self.events=queue.Queue(); self.busy=False; self.closed=False
        self.current=None; self.pending=[]
        self.status=tk.StringVar(value='Aggiorna per leggere la memoria delle letture.')
        self.refresh_button=ttk.Button(self,text='Aggiorna memoria',command=self.refresh)
        self.refresh_button.pack(anchor='w')
        ttk.Label(self,textvariable=self.status,wraplength=840).pack(anchor='w',pady=12)
        self.dashboard=tk.StringVar(value='QI: non misurato · Livello grammaticale A1–C2: non determinato.\nAggiorna per leggere i conteggi effettivi del motore.')
        ttk.Label(self,textvariable=self.dashboard,wraplength=860,justify='left',font=('DejaVu Sans',11,'bold')).pack(anchor='w',pady=(0,12))
        ttk.Button(self,text='Ultimi apprendimenti automatici',command=self.show_learning).pack(anchor='w',pady=(0,8))
        ttk.Button(self,text='Parole conosciute e ipotesi',command=self.show_vocabulary).pack(anchor='w',pady=(0,8))
        ttk.Button(self,text='Regole e percorso di miglioramento',command=self.show_rules).pack(anchor='w',pady=(0,8))
        self.summary=tk.StringVar(value='Le parole e le relazioni si sviluppano leggendo le fonti locali.')
        ttk.Label(self,textvariable=self.summary,wraplength=840,justify='left').pack(anchor='w',pady=(0,14))
        ttk.Label(self,text='Ambiguità nelle letture',font=('DejaVu Sans',13,'bold')).pack(anchor='w')
        self.listbox=tk.Listbox(self,height=5,exportselection=False,font=('DejaVu Sans',10),relief='flat',highlightthickness=1,highlightbackground='#DDE4EE',selectbackground='#EAF1FF',selectforeground='#172033')
        self.listbox.pack(fill='x',pady=8);self.listbox.bind('<<ListboxSelect>>',lambda event:self.select())
        self.context=tk.StringVar(value='I chiarimenti restano annotazioni dell’utente, da verificare nelle fonti.')
        ttk.Label(self,textvariable=self.context,wraplength=840,justify='left').pack(anchor='w',pady=8)
        self.answer=tk.Text(self,height=3,wrap='word',font=('DejaVu Sans',11),relief='flat',highlightthickness=1,highlightbackground='#DDE4EE',padx=10,pady=8)
        self.answer.pack(fill='x',pady=6)
        self.save_button=ttk.Button(self,text='Salva chiarimento da verificare',command=self.save,state='disabled')
        self.save_button.pack(anchor='w',pady=6)
        ttk.Label(self,text='La memoria non sostituisce le evidenze delle librerie selezionate. Questi conteggi non sono un livello linguistico o un punteggio di intelligenza.',wraplength=840).pack(anchor='w',pady=10)
        self.after_id=self.after(100,self.poll)

    def show_learning(self):
        if not self.current:self.refresh();return
        window=tk.Toplevel(self);window.title('Apprendimento dalle letture');window.geometry('820x550')
        text=tk.Text(window,wrap='word',padx=20,pady=20,font=('DejaVu Sans',11));text.pack(fill='both',expand=True)
        rows=self.current.get('learning_events',[])
        lines=['Apprendimento dalle sole fonti consultate. Nessuna modifica al codice del motore.','']
        for row in rows:
            lines.append(row['topic']+' · '+row['status'])
            if row['status']=='COMPLETED':
                growth=row['growth'];lines.append(f"Nuove osservazioni: {row['new_observations']}; nuove forme: {growth['FORME_LESSICALI']}; forme apprese: {growth['PAROLE_APPRESE']}; ipotesi: {growth['IPOTESI_LESSICALI']}.")
            if row.get('error'):lines.append(row['error'])
        if not rows:lines.append('Nessun apprendimento automatico registrato. Apri una voce in Studio o Enciclopedia; poi aggiorna la memoria.')
        lines+=['','Un’ipotesi lessicale non è un fatto verificato. L’apprendimento si può sospendere nelle Impostazioni.']
        text.insert('end','\n\n'.join(lines));text.configure(state='disabled')

    def show_vocabulary(self):
        if not self.current:self.refresh();return
        import json
        window=tk.Toplevel(self);window.title('Vocabolario di Wiki22');window.geometry('920x660')
        ttk.Label(window,text='Forme iniziali e acquisite nel modello; le ipotesi restano separate. Non è un conteggio di significati pienamente compresi.',wraplength=850).pack(padx=16,pady=12)
        bar=ttk.Frame(window);bar.pack(fill='x',padx=16)
        query=tk.StringVar();ttk.Entry(bar,textvariable=query).pack(side='left',fill='x',expand=True)
        category=tk.StringVar(value='Conosciute');ttk.Combobox(bar,textvariable=category,values=['Conosciute','Ipotesi','Tutte'],state='readonly',width=15).pack(side='left',padx=8)
        count=tk.StringVar();ttk.Label(window,textvariable=count).pack(anchor='w',padx=16,pady=8)
        tree=ttk.Treeview(window,columns=('form','status'),show='headings',height=12)
        tree.heading('form',text='Parola / forma');tree.heading('status',text='Stato nel modello')
        scrollbar=ttk.Scrollbar(window,command=tree.yview);tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right',fill='y');tree.pack(fill='both',expand=True,padx=16)
        detail=tk.Text(window,height=9,wrap='word',font=('DejaVu Sans',10));detail.pack(fill='x',padx=16,pady=12)
        rows=self.current['vocabulary'];shown=[]
        def refresh(*args):
            nonlocal shown
            shown=[r for r in rows if query.get().casefold() in r['form'].casefold() and (category.get()=='Tutte' or r['known']==(category.get()=='Conosciute'))]
            tree.delete(*tree.get_children());count.set(f'{len(shown)} corrispondenze · visualizzate le prime 500; restringi la ricerca per le altre')
            for i,r in enumerate(shown[:500]):tree.insert('', 'end',iid=str(i),values=(r['form'],r['status']))
            detail.configure(state='normal');detail.delete('1.0','end');detail.configure(state='disabled')
        def select(event):
            if not tree.selection():return
            r=shown[int(tree.selection()[0])];detail.configure(state='normal');detail.delete('1.0','end')
            detail.insert('end',r['form']+' — '+r['status']+'\n\nSignificati e riferimenti registrati nella memoria:\n'+json.dumps(r['meanings'],ensure_ascii=False,indent=2));detail.configure(state='disabled')
        query.trace_add('write',refresh);category.trace_add('write',refresh);tree.bind('<<TreeviewSelect>>',select);refresh()

    def show_rules(self):
        if not self.current:self.refresh();return
        d=self.current['dashboard'];window=tk.Toplevel(self);window.title('Grammatica e comprensione');window.geometry('850x620')
        text=tk.Text(window,wrap='word',padx=20,pady=20,font=('DejaVu Sans',11));text.pack(fill='both',expand=True)
        content='REGOLE DICHIARATE DEL NUCLEO LINGUISTICO\n\n'+'\n\n'.join(r['id']+' · '+r['struttura'] for r in d['grammar_details'])
        content+='\n\nLIMITI ATTUALI\n'+'\n'.join(d['limitations'])
        content+='\n\nCOME MIGLIORA\nLe letture registrate sviluppano parole e significati candidati. I chiarimenti dell’utente restano da verificare. Leggere più testi non aggiunge automaticamente nuove regole grammaticali.\n\nPer ampliare la comprensione occorre sviluppare e verificare nuove regole: subordinate, coordinazioni, pronomi e relazioni fra frasi. Ogni cambiamento va confrontato con domande nuove e casi contrari, misurando risposte corrette, errori e astensioni.\n\nI conteggi riguardano il nucleo linguistico, non tutte le regole del programma. QI e livello A1–C2 richiedono una valutazione calibrata: finché manca, restano non determinati.'
        text.insert('end',content);text.configure(state='disabled')

    def start(self, task):
        if self.busy:return
        self.busy=True;self.refresh_button.state(['disabled']);self.save_button.state(['disabled'])
        self.answer.configure(state='disabled');self.status.set('Lettura della memoria locale…')
        def worker():
            try:self.events.put(('ok',task()))
            except Exception as exc:self.events.put(('error',str(exc)))
        threading.Thread(target=worker,daemon=True).start()

    def refresh(self):
        self.start(lambda: snapshot(self.product_root))

    def select(self):
        if self.busy or not self.listbox.curselection():return
        row=self.pending[self.listbox.curselection()[0]]
        p=row['provenance']
        self.context.set(row['question']+'\nPassaggio letto: '+row['excerpt']+'\nFonte della lettura registrata: '+p['source'])
        self.save_button.state(['!disabled'])

    def save(self):
        if self.busy or not self.listbox.curselection():return
        question=self.pending[self.listbox.curselection()[0]]['id'];answer=self.answer.get('1.0','end').strip()
        def task():
            record_clarification(self.product_root,question,answer)
            return snapshot(self.product_root)
        self.start(task)

    def poll(self):
        if self.closed:return
        try:event=self.events.get_nowait()
        except queue.Empty:event=None
        if event:
            self.busy=False;self.refresh_button.state(['!disabled']);self.answer.configure(state='normal')
            if event[0]=='ok':
                self.current=event[1];r=self.current;g=r['growth_since_curriculum']
                d=r['dashboard']
                self.dashboard.set(f"QI: non misurato · Livello grammaticale A1–C2: non determinato\nParole conosciute nel modello: {d['known_forms']} forme (iniziali + acquisite)\nVocabolario: {d['vocabulary_forms']} forme registrate, di cui {d['hypotheses']} ipotesi; {d['acquired_forms']} forme apprese oltre il lessico iniziale\nLessico iniziale: {d['seed_forms']} forme · Grammatica di base: {d['grammar_productions']} produzioni + {d['morphology_patterns']} schemi morfologici · Ragionamento di base: {d['reasoning_rules']} regola")
                self.summary.set(f"{r['observations']} letture registrate · {r['user_assertions']} chiarimenti dell’utente\n"
                    f"Crescita rispetto al percorso iniziale: {g['words']} parole, {g['meanings']} significati contestuali, {g['entities']} entità e {g['relations']} relazioni.\n"
                    f"{g['propositions']} proposizioni supportate nel modello di lettura; {g['ambiguities_resolved']} ambiguità risolte dal contesto.")
                self.pending=[q for q in r['questions'] if not q['answered']]
                self.listbox.delete(0,'end')
                for q in self.pending:self.listbox.insert('end',q['question'])
                self.answer.delete('1.0','end');self.save_button.state(['disabled'])
                self.context.set('Scegli una domanda per leggere il contesto e aggiungere un chiarimento da verificare.' if self.pending else 'Nessuna ambiguità in attesa di chiarimento nelle letture registrate.')
                self.status.set('Memoria aggiornata. Le annotazioni dell’utente non autorizzano risposte fattuali.')
            else:
                self.status.set('Operazione non completata: '+event[1]);self.select()
        self.after_id=self.after(100,self.poll)

    def destroy(self):
        self.closed=True
        try:self.after_cancel(self.after_id)
        except tk.TclError:pass
        super().destroy()
