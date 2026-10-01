"""Maps and accessible outlines with citations from the selected local libraries."""
import tkinter as tk
from tkinter import ttk,filedialog
from pathlib import Path
from .encyclopedia_ui import EncyclopediaPanel
from .mindmap import compose_map,verify_map,map_layout,export_svg

class MindMapPanel(EncyclopediaPanel):
    def __init__(self,master,**kwargs):
        self.research_kind='Mappe'
        super().__init__(master,**kwargs)
        self.button.configure(text='Crea mappa')
        self.paper_canvas.pack_forget()
        for child in self.body.winfo_children():child.pack_forget()
        modes=ttk.Frame(self.body);modes.pack(fill='x')
        self.map_mode=tk.StringVar(value='Mappa')
        for label in ('Mappa','Schema'):
            ttk.Radiobutton(modes,text=label,variable=self.map_mode,value=label,command=self.show_page).pack(side='left',padx=8,pady=8)
        ttk.Button(modes,text='Apri Enciclopedia',command=lambda:self.navigate('Articles')).pack(side='right',padx=8)
        self.map_frame=tk.Frame(self.body,bg='#F1F5F0');self.map_frame.pack(fill='both',expand=True)
        self.map_canvas=tk.Canvas(self.map_frame,bg='#F1F5F0',highlightthickness=0)
        sy=ttk.Scrollbar(self.map_frame,orient='vertical',command=self.map_canvas.yview);sx=ttk.Scrollbar(self.map_frame,orient='horizontal',command=self.map_canvas.xview)
        sy.pack(side='right',fill='y');sx.pack(side='bottom',fill='x');self.map_canvas.pack(fill='both',expand=True)
        self.map_canvas.configure(yscrollcommand=sy.set,xscrollcommand=sx.set)
        self.outline=ttk.Treeview(self.body,columns=('source',),show='tree headings');self.outline.heading('#0',text='Argomento / passaggio');self.outline.heading('source',text='Fonte');self.outline.column('#0',width=700);self.outline.column('source',width=60)
        self.outline.bind('<<TreeviewSelect>>',self.select_node)
        self.previous.grid_remove();self.next.grid_remove();self.counter_label.grid_remove()
        self.export_button.configure(text='Salva mappa e fonti…')
        self.map_canvas.create_text(30,40,anchor='nw',text='Cerca una voce per costruire una mappa con le sue fonti.',font=('DejaVu Sans',13))
        self.map_result=None

    def write(self,blocks):
        if not hasattr(self,'map_canvas'):return super().write(blocks)
        self.map_result=None;self.outline.delete(*self.outline.get_children());self.map_canvas.delete('all')
        self.map_canvas.create_text(30,40,anchor='nw',text='\n\n'.join(t for t,tag in blocks),width=750,font=('DejaVu Sans',12))

    def show_page(self):
        if not self.result or self.result['status']!='READY':return
        doc=self.result['document'];book=self.result['book']
        self.map_result=compose_map(doc,book);r=self.map_result
        self.outline.delete(*self.outline.get_children());self.note_ids={}
        root=self.outline.insert('','end',text=r['title'],open=True)
        for b in r['branches']:
            branch=self.outline.insert(root,'end',text=b['title'],open=True)
            for item in b['items']:
                node=self.outline.insert(branch,'end',text=item['text'],values=(f"[{item['note']}]",));self.note_ids[node]=item['note']
        if self.map_mode.get()=='Schema':
            self.map_frame.pack_forget();self.outline.pack(fill='both',expand=True)
        else:
            self.outline.pack_forget();self.map_frame.pack(fill='both',expand=True)
            c=self.map_canvas;c.delete('all');layout=map_layout(r);c.configure(scrollregion=(0,0,layout['width'],layout['height']))
            for line in layout['lines']:c.create_line(*line,fill='#739381',width=2)
            nodes=[dict(x=25,y=55,w=250,h=105,title=r['title'],items=[])]+layout['nodes']
            for n in nodes:
                x,y,w,h=n['x'],n['y'],n['w'],n['h'];c.create_rectangle(x,y,x+w,y+h,fill='white',outline='#ACC3B4',width=2)
                if n['title']:c.create_text(x+15,y+20,anchor='nw',text=n['title'],width=w-30,font=('DejaVu Sans',12,'bold'),fill='#203A2C')
                yy=y+15
                for item in n['items']:
                    tag='source_'+str(item['note']);obj=c.create_text(x+15,yy,anchor='nw',text=item['text']+f" [{item['note']}]",width=w-30,font=('DejaVu Sans',10),fill='#245E49',tags=(tag,))
                    yy=c.bbox(obj)[3]+18;c.tag_bind(tag,'<Button-1>',lambda e,num=item['note']:self.citation(num))
                    c.tag_bind(tag,'<Enter>',lambda e:c.configure(cursor='hand2'));c.tag_bind(tag,'<Leave>',lambda e:c.configure(cursor=''))
            c.yview_moveto(0);c.xview_moveto(0)
        self.export_button.state(['!disabled']);self.study_button.state(['!disabled'])
        self.status.set(f"{len(r['branches'])} sezioni su {r['available_sections']} · Clicca un passaggio per la fonte. "+r['scope'])

    def select_node(self,event=None):
        selected=self.outline.selection()
        if selected and selected[0] in self.note_ids:self.citation(self.note_ids[selected[0]])

    def export(self):
        if self.busy or not self.map_result:return
        try:
            book=self.checked_book();doc=self.result['document'];verify_map(self.map_result,doc,book)
            from .research_document import export_html
            # One standalone HTML contains the SVG and full numbered source notes.
            svg=export_svg(self.map_result,doc,book);html=export_html(doc,book)
            html=html.replace('<article class="page">','<div style="overflow:auto">'+svg+'</div><article class="page">',1)
            name=filedialog.asksaveasfilename(parent=self,title='Salva mappa con fonti',defaultextension='.html',initialfile='Wiki22-mappa.html',filetypes=[('Mappa e fonti','*.html')])
            if name:Path(name).write_text(html,encoding='utf-8');self.status.set('Mappa e fonti salvate nello stesso documento.')
        except Exception as exc:self.status.set(str(exc))
