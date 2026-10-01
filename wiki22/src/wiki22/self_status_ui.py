"""Product-facing self inspection; all work runs away from Tk's event thread."""
import json
import queue
import threading
import tkinter as tk
from tkinter import ttk

from wiki22.self_inspection.service import SelfInspection
from .maturity import Assessment,describe_assessment
from .maturity_profile import BANDS,DESCRIPTORS
from .system_profile import system_profile,describe

PROBE_LABELS = {
    'WIKI22-language_learning_and_reflection': 'Apprendimento e controllo delle risposte',
    'WIKI22-compact_reading_and_semantic_gate': 'Lettura e ricerca nelle librerie 22CK',
    'WIKI22-persistent_observation_and_replay': 'Memoria delle letture dopo il riavvio',
    'WIKI22-offline_enforcement': 'Blocco delle connessioni di rete',
}


def readable_report(summary, probes):
    lines = ['Verifiche eseguite sul codice installato', '']
    for probe in probes:
        state = 'Verificato' if probe['status'] == 'PASS' else 'Non verificato'
        lines.append(state + ' · ' + PROBE_LABELS.get(probe['probe_id'], 'Sonda locale'))
    lines += ['', f"{summary['probe_pass']} prove riuscite su {summary['probe_total']}.",
              f"{summary['verified_capabilities']} capacità strutturali confermate dalle prove.",
              '', 'Le prove usano casi controllati. Non dimostrano la comprensione di ogni testo',
              'né sostituiscono la verifica dell’intero corpus e del dispositivo USB.']
    return '\n'.join(lines)


class SelfStatusPanel(ttk.Frame):
    def __init__(self, master, *, product_root):
        super().__init__(master)
        self.product_root = product_root
        self.assessment=Assessment(product_root)
        self.service = None
        self.results = queue.Queue()
        self.busy = False
        self.closed = False
        self.summary = None
        self.status = tk.StringVar(value='Nessuna verifica eseguita in questa sessione.')
        ttk.Label(self, text='Capacità dimostrate, con le loro prove.', font=('DejaVu Sans', 16, 'bold')).pack(anchor='w', pady=(12, 6))
        ttk.Label(self, text='Wiki22 legge il proprio codice e prova i percorsi autorizzati in una copia temporanea.',
                  wraplength=780).pack(anchor='w', pady=(0, 16))
        actions = ttk.Frame(self)
        actions.pack(fill='x')
        self.verify_button = ttk.Button(actions, text='Verifica adesso', command=self.verify)
        self.verify_button.pack(side='left')
        self.details_button = ttk.Button(actions, text='Mostra le prove', command=self.show_details, state='disabled')
        self.details_button.pack(side='left', padx=10)
        self.maturity_button=ttk.Button(actions,text='Valuta A1–C2 / QI',command=self.evaluate);self.maturity_button.pack(side='left',padx=6)
        self.identity_button=ttk.Button(actions,text='Chi sono e tecnologie',command=self.describe_system);self.identity_button.pack(side='left')
        ttk.Label(self, textvariable=self.status, wraplength=800).pack(anchor='w', pady=14)
        self.profile_frame=ttk.Frame(self)
        self.profile_frame.pack(fill='x',pady=(0,8))
        self.report_body=ttk.Frame(self);self.report_body.pack(fill='both',expand=True,pady=(0,12))
        self.report_scroll=ttk.Scrollbar(self.report_body);self.report_scroll.pack(side='right',fill='y')
        self.report = tk.Text(self.report_body, wrap='word', font=('DejaVu Sans', 11), height=10, relief='flat', padx=18, pady=18, state='disabled')
        self.report.configure(yscrollcommand=self.report_scroll.set);self.report_scroll.configure(command=self.report.yview)
        self.report.pack(fill='both', expand=True)
        self.task_button=ttk.Button(self,text='Dettaglio dei compiti',command=self.show_tasks,state='disabled');self.task_button.pack(side='bottom',anchor='e',pady=(0,8),before=self.report_body)
        self.poll_id = self.after(100, self.poll)

    def write(self, text):
        self.report.configure(state='normal')
        self.report.delete('1.0', 'end')
        self.report.insert('1.0', text)
        self.report.configure(state='disabled')

    def evaluate(self):
        self.background('maturity',self.assessment.run)

    def describe_system(self):
        self.background('profile',lambda:system_profile(self.product_root))

    def background(self,kind,task):
        if self.busy:return
        self.busy=True;self.status.set('Misurazione locale in corso…')
        self.task_button.state(['disabled'])
        for child in self.profile_frame.winfo_children():child.destroy()
        self.verify_button.configure(state='disabled');self.details_button.configure(state='disabled')
        def work():
            try:self.results.put((kind,task()))
            except Exception as error:self.results.put(('error',type(error).__name__+': '+str(error)))
        threading.Thread(target=work,daemon=True).start()

    def verify(self):
        if self.busy:
            return
        self.busy = True
        self.verify_button.configure(state='disabled')
        self.details_button.configure(state='disabled')
        self.status.set('Verifica locale in corso…')
        def work():
            try:
                service = SelfInspection(self.product_root)
                summary = service.inspect()
                readback = service.answer('Che cosa sai fare?')
                if readback['STATO'] != 'VERIFICATA' or summary['probe_pass'] != summary['probe_total']:
                    raise ValueError('Le prove non sono tutte riuscite o i sorgenti sono cambiati. Ripeti la verifica dopo aver risolto il problema.')
                self.results.put(('ok', service, summary))
            except Exception as error:
                self.results.put(('error', type(error).__name__ + ': ' + str(error)))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        if self.closed:
            return
        try:
            event = self.results.get_nowait()
        except queue.Empty:
            event = None
        if event:
            self.busy = False
            self.verify_button.configure(state='normal')
            if event[0]=='maturity':
                try:
                    self.show_profile(self.assessment.current()['profile']);self.task_button.state(['!disabled']);self.write(describe_assessment(self.assessment.current()));self.status.set('Prove interne completate. Anche i compiti non risolti sono mostrati.')
                except ValueError as error:
                    self.write(str(error));self.status.set('Valutazione da ripetere: nessun risultato corrente confermato.')
            elif event[0]=='profile':
                self.write(describe(event[1]));self.status.set('Descrizione ricavata da metadata, codice e lettori delle librerie.')
            elif event[0] == 'ok':
                _, self.service, self.summary = event
                self.status.set('Verifica completata. Le prove si riferiscono a questa versione del codice.')
                self.write(readable_report(self.summary, self.service.probes))
                self.details_button.configure(state='normal')
            else:
                self.service = None
                self.summary = None
                self.status.set('Verifica non completata. Nessuna capacità viene confermata.')
                self.write(event[1])
        self.poll_id = self.after(100, self.poll)

    def show_profile(self,p):
        for child in self.profile_frame.winfo_children():child.destroy()
        headline=f"Ragionamento 22: {p['reasoning']['solved']}/{p['reasoning']['total']}  ·  Fascia interna: {p['internal_band'] or 'incompleta'}  ·  QI umano: non calibrato  ·  Parlato: non valutato"
        ttk.Label(self.profile_frame,text=headline,font=('DejaVu Sans',12,'bold')).grid(row=0,column=0,columnspan=6,sticky='w',pady=(0,6))
        for i,band in enumerate(BANDS):
            g=p['bands'][band];cell=ttk.Frame(self.profile_frame,padding=(6,3));cell.grid(row=1,column=i,sticky='ew');self.profile_frame.columnconfigure(i,weight=1)
            ttk.Label(cell,text=f"{band} · {g['solved']}/{g['total']}").pack(anchor='w')
            ttk.Progressbar(cell,maximum=g['total'],value=g['solved'],length=70).pack(fill='x')
        ttk.Label(self.profile_frame,text='Compiti interni ispirati alle fasce: non è una certificazione CEFR. Errori e astensioni sono inclusi.',wraplength=850).grid(row=2,column=0,columnspan=6,sticky='w',pady=(6,0))
    def show_tasks(self):
        try:receipt=self.assessment.current()
        except ValueError as exc:self.status.set(str(exc));self.task_button.state(['disabled']);return
        if not receipt:return
        rows=receipt['profile']['cases']
        window=tk.Toplevel(self);window.title('Wiki22 · Prove di lingua e ragionamento');window.geometry('960x700')
        ttk.Label(window,text='Seleziona un compito per confrontare premesse, obiettivo e risposta effettiva.',padding=12).pack(anchor='w')
        frame=ttk.Frame(window);frame.pack(fill='both',expand=True,padx=12)
        scroll=ttk.Scrollbar(frame);scroll.pack(side='right',fill='y')
        tree=ttk.Treeview(frame,columns=('area','result','task'),show='headings',height=12,yscrollcommand=scroll.set);scroll.configure(command=tree.yview)
        tree.heading('area',text='Fascia / dominio');tree.heading('result',text='Esito');tree.heading('task',text='Compito')
        tree.column('area',width=150,stretch=False);tree.column('result',width=130,stretch=False);tree.column('task',width=600)
        tree.pack(fill='both',expand=True)
        for i,r in enumerate(rows):
            outcome='Riuscito' if r['passed'] else 'Astensione' if r['abstained'] else 'Risposta errata'
            tree.insert('', 'end',iid=str(i),values=(r.get('band') or r.get('domain') or 'Prudenza',outcome,r.get('question',r['text'])))
        detail_frame=ttk.Frame(window);detail_frame.pack(fill='both',expand=True,padx=12,pady=12)
        ds=ttk.Scrollbar(detail_frame);ds.pack(side='right',fill='y')
        detail=tk.Text(detail_frame,wrap='word',height=13,font=('DejaVu Sans',10),padx=12,pady=12,yscrollcommand=ds.set);detail.pack(fill='both',expand=True);ds.configure(command=detail.yview)
        def select(event=None):
            if not tree.selection():return
            r=rows[int(tree.selection()[0])]
            text=r['id']+'\n\nPREMESSE\n'+r['text']+'\n\nCOMPITO\n'+r.get('question','Analisi di soggetto, complemento, negazione e tempo')
            if r.get('antecedents'):text+='\nAntecedenti: '+', '.join(r['antecedents'])
            text+='\n\nATTESO\n'+json.dumps(r['expected'],ensure_ascii=False,indent=2)+'\n'+r.get('expected_status','')
            text+='\n\nOSSERVATO\n'+json.dumps(r['actual'],ensure_ascii=False,indent=2)+'\n'+str(r['status'])
            text+=f"\n\nTempo del compito: {r['milliseconds']} ms (non latenza dell’intera interfaccia).\nBatteria: {receipt['profile']['suite']}\nLa prova non modifica la memoria personale."
            detail.configure(state='normal');detail.delete('1.0','end');detail.insert('end',text);detail.configure(state='disabled')
        tree.bind('<<TreeviewSelect>>',select)
        tree.selection_set('0');select()

    def show_details(self):
        if self.service is None:
            return
        result = self.service.answer('Che cosa sai fare?')
        if result['STATO'] != 'VERIFICATA':
            self.status.set('I sorgenti sono cambiati: ripeti la verifica.')
            self.details_button.configure(state='disabled')
            self.write('Le prove precedenti non sono più valide per il codice attuale.')
            return
        self.write(json.dumps({'summary': self.summary, 'probes': self.service.probes,
                               'source_readback': result}, ensure_ascii=False, indent=2))

    def destroy(self):
        self.closed = True
        try:
            self.after_cancel(self.poll_id)
        except tk.TclError:
            pass
        super().destroy()
