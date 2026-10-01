"""Documentary maps: section membership is not a claim of causal relation."""
from .research_document import verify_document,digest
from html import escape
import textwrap

def compose_map(document,book,limit=12):
    verify_document(document,book)
    if type(limit) is not int or not 1<=limit<=24:raise ValueError('Limite mappa non valido')
    groups={}
    for note in document['notes']:
        groups.setdefault(note['heading'] or 'Introduzione',[]).append(note)
    branches=[]
    for heading,notes in list(groups.items())[:limit]:
        # Keep entire cited sentences; no generated relation or meaning.
        branches.append(dict(title=heading,items=[dict(text=n['excerpt'],note=n['number']) for n in notes[:2]],available=len(notes)))
    result=dict(schema='wiki22.documentary.map.v1',title=book['title'],branches=branches,
        document_sha256=document['document_sha256'],book_sha256=digest(book),
        available_sections=len(groups),scope='Schema delle sezioni e dei passaggi selezionati; i rami indicano appartenenza al testo, non cause o deduzioni.')
    result['sha256']=digest(result)
    return result

def verify_map(result,document,book):
    if result!=compose_map(document,book,limit=12):raise ValueError('Mappa o fonte cambiate: riapri la voce.')
    return True

def map_layout(result):
    nodes=[];lines=[];y=90
    for i,b in enumerate(result['branches']):
        height=max(110,50+sum((len(textwrap.wrap(x['text'],width=65)) or 1)*18+25 for x in b['items']))
        nodes.append(dict(x=350,y=y,w=230,h=height,title=b['title'],items=[],branch=i))
        nodes.append(dict(x=640,y=y,w=540,h=height,title='',items=b['items'],branch=i))
        lines.extend([(275,80,315,y+height/2),(315,y+height/2,350,y+height/2),(580,y+height/2,640,y+height/2)])
        y+=height+26
    return dict(width=1220,height=max(420,y+40),nodes=nodes,lines=lines)

def export_svg(result,document,book):
    verify_map(result,document,book);layout=map_layout(result);esc=escape
    pieces=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{layout["width"]}" height="{layout["height"]}" viewBox="0 0 {layout["width"]} {layout["height"]}"><title>'+esc(result['title'])+'</title><rect width="100%" height="100%" fill="#f1f5f0"/>']
    pieces.append('<text x="30" y="35" font-family="sans-serif" font-size="16">Wiki22 · Mappa documentaria · fonti numerate</text>')
    for x1,y1,x2,y2 in layout['lines']:pieces.append(f'<path d="M{x1},{y1} L{x2},{y2}" fill="none" stroke="#739381" stroke-width="2"/>')
    nodes=[dict(x=25,y=55,w=250,h=105,title=result['title'],items=[])]+layout['nodes']
    for n in nodes:
        pieces.append(f'<rect x="{n["x"]}" y="{n["y"]}" width="{n["w"]}" height="{n["h"]}" rx="12" fill="white" stroke="#acc3b4"/>')
        y=n['y']+25
        for line in textwrap.wrap(n['title'],width=25):
            pieces.append(f'<text x="{n["x"]+14}" y="{y}" font-family="sans-serif" font-size="14">{esc(line)}</text>');y+=18
        for item in n['items']:
            for line in textwrap.wrap(item['text']+' ['+str(item['note'])+']',width=65):
                pieces.append(f'<text x="{n["x"]+14}" y="{y}" font-family="sans-serif" font-size="13">{esc(line)}</text>');y+=18
            y+=18
    pieces.append('</svg>');return ''.join(pieces)
