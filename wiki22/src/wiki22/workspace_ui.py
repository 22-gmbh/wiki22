"""History, persistent configuration and measured language dashboard."""
import tkinter as tk
from tkinter import ttk
from .workspace_state import WorkspaceState

class HistoryPanel(ttk.Frame):
    def __init__(self,master,*,workspace,on_navigate):
        super().__init__(master);self.workspace=workspace;self.navigate=on_navigate;self.rows=[]
        self.filter=tk.StringVar();entry=ttk.Entry(self,textvariable=self.filter);entry.pack(fill='x')
        self.filter.trace_add('write',lambda *args:self.refresh())
        ttk.Label(self,text='Filtra le ricerche. Seleziona una riga e riprendila nella vista che preferisci.').pack(anchor='w',pady=10)
        self.list=tk.Listbox(self,exportselection=False,font=('DejaVu Sans',11),height=12);self.list.pack(fill='both',expand=True)
        self.list.bind('<Double-Button-1>',lambda e:self.open('Articles'))
        bar=ttk.Frame(self);bar.pack(fill='x',pady=12)
        for label,target in [('Apri in Chat','Chat'),('Apri in Studio','Study'),('Leggi in Enciclopedia','Articles'),('Apri mappa','Maps')]:
            ttk.Button(bar,text=label,command=lambda t=target:self.open(t)).pack(side='left',padx=4)
        self.status=tk.StringVar();ttk.Label(self,textvariable=self.status,wraplength=850).pack(anchor='w')
        self.refresh()
    def refresh(self):
        self.rows=self.workspace.recent(self.filter.get());self.list.delete(0,'end')
        for r in self.rows:self.list.insert('end',f"{r['at'][:10]} · {r['kind']} · {r['query']}")
        self.status.set(f'{len(self.rows)} ricerche recenti visualizzate. Restano sul PC; non diventano conoscenza verificata.' if self.rows else 'Nessuna ricerca salvata. La cronologia inizierà dalle prossime ricerche; si può disattivare nelle Impostazioni.')
    def open(self,target):
        if not self.list.curselection():return
        r=self.rows[self.list.curselection()[0]]
        self.navigate(target,r['topic'],r['scope'],query=r['query'] if target=='Chat' else None)

class ConfigurationPanel(ttk.Frame):
    def __init__(self,master,*,workspace,on_save):
        super().__init__(master);self.workspace=workspace;self.on_save=on_save;p=workspace.preferences()
        self.pages=tk.StringVar(value=str(p['article_pages']));self.font=tk.StringVar(value=str(p['reading_font']))
        self.check=tk.StringVar(value='Approfondita' if p['verification']=='deep' else 'Standard')
        self.remember=tk.BooleanVar(value=p['remember_searches'])
        self.learn=tk.BooleanVar(value=p['automatic_learning']);self.budget=tk.StringVar(value=str(p['learning_budget']))
        for label,var,values in [('Lunghezza massima in Enciclopedia (pagine)',self.pages,[str(n) for n in range(1,13)]),('Dimensione del testo in Studio ed Enciclopedia',self.font,['11','13','15']),('Verifica delle fonti in Enciclopedia',self.check,['Standard','Approfondita'])]:
            row=ttk.Frame(self);row.pack(fill='x',pady=6)
            ttk.Label(row,text=label,width=55).pack(side='left');ttk.Combobox(row,textvariable=var,values=values,state='readonly',width=18).pack(side='left')
        ttk.Label(self,text='Standard: lettura autenticata e controllo finale. Approfondita: ulteriore rilettura della fonte.\nQuesta scelta aggiunge controlli; non aumenta il QI e non attiva un LLM.',wraplength=840,justify='left').pack(anchor='w',pady=8)
        ttk.Checkbutton(self,text='Impara in sottofondo dalle fonti che consulto',variable=self.learn).pack(anchor='w',pady=6)
        learning_row=ttk.Frame(self);learning_row.pack(fill='x')
        ttk.Label(learning_row,text='Massimo di evidenze per argomento',width=55).pack(side='left')
        ttk.Combobox(learning_row,textvariable=self.budget,values=['1','3','8'],state='readonly',width=18).pack(side='left')
        ttk.Label(self,text='La pausa interrompe i nuovi apprendimenti dopo l’evidenza in corso; conserva la memoria. Non legge documenti esterni alle librerie selezionate.',wraplength=840).pack(anchor='w',pady=6)
        ttk.Checkbutton(self,text='Conserva sul dispositivo le nuove ricerche',variable=self.remember).pack(anchor='w',pady=6)
        ttk.Label(self,text='Disattivare la cronologia conserva le ricerche precedenti. Offline e verifica delle fonti restano sempre attivi.',wraplength=840).pack(anchor='w',pady=6)
        ttk.Button(self,text='Salva configurazione',command=self.save).pack(anchor='w',pady=8)
        self.status=tk.StringVar(value='Le modifiche valgono dalle prossime letture.');ttk.Label(self,textvariable=self.status).pack(anchor='w')
    def save(self):
        try:
            p=self.workspace.save_preferences(dict(article_pages=int(self.pages.get()),reading_font=int(self.font.get()),verification='deep' if self.check.get()=='Approfondita' else 'standard',remember_searches=self.remember.get(),automatic_learning=self.learn.get(),learning_budget=int(self.budget.get())))
            self.on_save(p);self.status.set('Configurazione salvata. Verrà mantenuta al prossimo avvio.')
        except Exception as exc:self.status.set('Configurazione non salvata: '+str(exc))
