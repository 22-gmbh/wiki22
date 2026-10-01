"""Import fidelity, bounded learning and source-scope tests on disposable data."""
import os
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
import zipfile
from wiki22.encyclopedia_service import EncyclopediaService
from wiki22.document_import import extract,formats,ImportedProvider,MAX_FILE
from wiki22.encyclopedia_intelligence import graph,memory,observe,reason


def archive(path,files):
    with zipfile.ZipFile(path,'w') as z:
        for name,body in files.items():z.writestr(name,body)

def epub(path):
    archive(path,{'mimetype':'application/epub+zip',
      'META-INF/container.xml':'<container><rootfiles><rootfile full-path="OEBPS/book.opf"/></rootfiles></container>',
      'OEBPS/book.opf':'<package xmlns="http://www.idpf.org/2007/opf"><manifest><item id="a" href="first.xhtml"/><item id="b" href="second.xhtml"/></manifest><spine><itemref idref="b"/><itemref idref="a"/></spine></package>',
      'OEBPS/first.xhtml':'<html><body><p>Capitolo finale: Gauss nacque nel 1777.</p></body></html>',
      'OEBPS/second.xhtml':'<html><head><title>Da ignorare</title></head><body><p>Primo capitolo: Roma è in Italia.</p><script>NON TESTO</script></body></html>'})

def pdf(path,text='La biblioteca conserva documenti storici.'):
    stream=f'BT /F1 12 Tf 72 720 Td ({text}) Tj ET'.encode()
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream']
    body=b'%PDF-1.4\n';offsets=[0]
    for i,o in enumerate(objects,1):offsets.append(len(body));body+=str(i).encode()+b' 0 obj\n'+o+b'\nendobj\n'
    start=len(body);body+=b'xref\n0 6\n0000000000 65535 f \n'+b''.join(f'{x:010d} 00000 n \n'.encode() for x in offsets[1:])+f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF'.encode();path.write_bytes(body)

class Import56Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name);self.s=EncyclopediaService(self.base/'app')
        self.addCleanup(self.temp.cleanup);self.addCleanup(self.s.close)
    def add(self,title,text):
        p=self.base/(title+'.txt');p.write_text(text);return self.s.import_library(str(p),title)
    def doc(self,lid):
        r=self.s.search('',mode='SINGLE',ids=[lid])['rows'][0]
        return self.s.article(lid,r['article_id'],mode='SINGLE',ids=[lid])
    def ref(self,d):return {k:d[k] for k in ('library_id','article_id','source_hash')}
    def test_compact_magic_case_punctuation_provenance(self):
        r=self.add('Archivio','Roma è la capitale d’Italia. Non è Milano!');p=self.s.registry.resolve_pack(r['id'])
        catalog=json.loads(p.read_text());self.assertEqual((p.parent/catalog['parts'][0]['path']).read_bytes()[:8],b'22CKV003')
        d=self.doc(r['id']);self.assertIn('Roma è la capitale d’Italia.',d['notes'][0]['excerpt']);self.assertIn('#sha256=',d['notes'][0]['source'])
        self.assertEqual(r['format'],'22CK V3');self.assertTrue(d['complete'])
    def test_epub_spine_order_and_script_removed(self):
        p=self.base/'Libro.epub';epub(p);before=p.read_bytes();r=self.s.import_library(str(p),'Libro');d=self.doc(r['id'])
        text=' '.join(n['excerpt'] for n in d['notes']);self.assertLess(text.index('Primo'),text.index('finale'));self.assertNotIn('NON TESTO',text);self.assertEqual(p.read_bytes(),before)
    def test_docx_odt_fb2_html_csv_pptx(self):
        folder=self.base/'documenti';folder.mkdir()
        archive(folder/'Lettera.docx',{'word/document.xml':'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Una lettera italiana.</w:t></w:r></w:p></w:body></w:document>'})
        archive(folder/'Saggio.odt',{'content.xml':'<document><p>Il saggio contiene una tesi.</p></document>'})
        archive(folder/'Slide.pptx',{'ppt/slides/slide1.xml':'<a:sld xmlns:a="urn:a"><a:p><a:r><a:t>Prima diapositiva.</a:t></a:r></a:p></a:sld>'})
        (folder/'Libro.fb2').write_text('<FictionBook><body><section><p>Una storia documentata.</p></section></body></FictionBook>')
        (folder/'Pagina.html').write_text('<h1>Una pagina</h1><p>Testo &amp; cultura.</p><script>bad()</script>')
        (folder/'Dati.csv').write_text('anno,evento\n1918,Armistizio\n')
        r=self.s.import_library(str(folder),'Documenti');self.assertEqual(r['articles'],6);self.assertEqual(r['status'],'IMPORTED')
        for row in self.s.search('',mode='SINGLE',ids=[r['id']])['rows']:
            d=self.s.article(r['id'],row['article_id']);self.assertTrue(d['notes'])
    @unittest.skipUnless(shutil.which('pdftotext'),'Poppler absent')
    def test_pdf_real_conversion_page_source_and_blank(self):
        p=self.base/'Prova.pdf';pdf(p);before=p.read_bytes();r=self.s.import_library(str(p),'PDF');d=self.doc(r['id'])
        self.assertIn('biblioteca',d['notes'][0]['excerpt']);self.assertEqual(d['notes'][0]['heading'],'Pagina 1');self.assertEqual(p.read_bytes(),before)
        pdf(p,'');r=self.s.import_library(str(p),'Vuoto');self.assertIsNone(r['id']);self.assertIn('OCR',r['report'][0]['reason'])
    def test_mixed_report_and_zero_import_no_registry_row(self):
        folder=self.base/'mixed';folder.mkdir();(folder/'ok.txt').write_text('Testo italiano.');(folder/'video.mp4').write_bytes(b'not readable')
        r=self.s.import_library(str(folder),'Misti');self.assertEqual(r['status'],'PARTIAL');self.assertEqual(r['articles'],1);self.assertEqual(len(r['report']),2)
        p=folder/'video.mp4';r=self.s.import_library(str(p),'Video');self.assertEqual(r['status'],'NOT_IMPORTED');self.assertIsNone(self.s.registry.get('video'))
    def test_bad_archives_xml_entities_symlink(self):
        folder=self.base/'bad';folder.mkdir();archive(folder/'escape.epub',{'../outside':'x'})
        (folder/'entities.fb2').write_text('<!DOCTYPE x [<!ENTITY a "boom">]><FictionBook><p>&a;</p></FictionBook>')
        if os.name!='nt':(folder/'link.txt').symlink_to(self.base/'missing')
        r=self.s.import_library(str(folder),'Bad');self.assertIsNone(r['id']);self.assertEqual(len(r['report']),2 if os.name=='nt' else 3)
        self.assertFalse((self.base/'outside').exists())
    def test_document_sidecar_tamper_fails_closed(self):
        r=self.add('Fonte','Una fonte stabile.');d=self.doc(r['id']);path=self.s.registry.resolve_pack(r['id']).parent/'documents.sqlite3'
        db=sqlite3.connect(path)
        try:
            with db:db.execute("UPDATE documents SET body='{}'")
        finally:db.close()
        with self.assertRaises(ValueError):self.doc(r['id'])
        self.s.close()
        with self.assertRaises(ValueError):self.doc(r['id'])
    def test_observation_deduplicated_and_replayed_without_shelf(self):
        r=self.add('Roma','Roma è una città. Roma si trova in Italia.');d=self.doc(r['id']);ref=self.ref(d)
        result=observe(self.s,ref,mode='SINGLE',ids=[r['id']]);self.assertEqual(result['new_observations'],1)
        self.assertEqual(observe(self.s,ref)['new_observations'],0);self.assertEqual(memory(self.s)['observations'],1);self.assertEqual(self.s.shelf(),[])
        other=EncyclopediaService(self.s.root)
        try:self.assertEqual(memory(other)['observations'],1)
        finally:other.close()
    def test_learning_reasoning_graph_respect_scope_and_stale_identity(self):
        r=self.add('Roma','Roma è una città. Roma si trova in Italia.');d=self.doc(r['id']);ref=self.ref(d)
        b=self.add('Parigi','Parigi si trova in Francia.')
        for f,args in [(observe,{}),(reason,{'question':'Dove si trova Roma?'})]:
            with self.assertRaises(ValueError):f(self.s,ref,mode='SINGLE',ids=[b['id']],**args)
            with self.assertRaises(ValueError):f(self.s,{**ref,'source_hash':'forged'},**args)
        g=graph(self.s,'Roma',mode='SINGLE',ids=[r['id']]);self.assertEqual(g['scope'],[r['id']]);self.assertTrue(g['nodes'])
        resolved=graph(self.s,'Roma',mode='SINGLE',ids=[r['id']],node=g['nodes'][0]['id'])
        self.assertTrue(resolved['evidence']);self.assertTrue(all(e['library_id']==r['id'] for e in resolved['evidence']))
        with self.assertRaises(KeyError):graph(self.s,'Roma',mode='SINGLE',ids=[r['id']],node='forged')
        answer=reason(self.s,ref,'Dove si trova Roma?');self.assertEqual(answer['MODEL_CALLS'],0)
        for f in answer['FONTI']:self.assertEqual(f['provenance']['library_id'],r['id'])
    def test_native_multistep_proof_and_missing_rule_abstention(self):
        r=self.add('Percorso','Arla precede Melda. Melda precede Neria. Precede è una relazione transitiva.')
        d=self.doc(r['id']);answer=reason(self.s,self.ref(d),'Arla precede Neria?')
        self.assertEqual(answer['STATO'],'VERIFICATA');self.assertEqual(answer['VALORE'],'sì');self.assertEqual(len(answer['FONTI']),3)
        for f in answer['FONTI']:
            e=self.s.provider(r['id']).get_evidence(f['provenance']['evidence_id'])
            self.assertEqual(e.text[slice(*f['TEXT_SPAN'])],f['testo'])
        r=self.add('Senza regola','Arla precede Melda. Melda precede Neria.')
        answer=reason(self.s,self.ref(self.doc(r['id'])),'Arla precede Neria?')
        self.assertNotEqual(answer['STATO'],'VERIFICATA')
    def test_learning_preference_validated_and_persistent(self):
        self.s.save_preferences({'automatic_learning':True,'learning_budget':8});self.assertTrue(self.s.preferences()['automatic_learning'])
        for prefs in ({'automatic_learning':'true'},{'learning_budget':100}):
            with self.assertRaises(ValueError):self.s.save_preferences(prefs)
    def test_timeline_keeps_normalized_bce_and_ignores_url_numbers(self):
        from wiki22.encyclopedia_context import date_mentions
        r=self.add('Cronaca','Nel iii secolo a . c . Roma si espanse. Nel iv secolo d . c . iniziò un nuovo periodo.')
        d=self.doc(r['id']);t=self.s.timeline([self.ref(d)])
        self.assertEqual([e['date']['start'] for e in t['events']],[-300,301])
        self.assertEqual(date_mentions('it / storia / articoli / 2019 / 01 / gli - anni - c1178c6f - 1279 - 46f7 .'),[])
        self.assertEqual([x['start'] for x in date_mentions('Nel 1918. https : / / example . org / 2025 / 1279')],[1918])
    def test_extended_wikipedia_style_reading_keeps_era_before_filtering(self):
        from unittest.mock import patch
        from wiki22.extended_reading import open_extended
        from wiki22.encyclopedia_service import documentary_sentences
        text='Con la fondazione di Roma da parte dei popoli latini, secondo la leggenda da Romolo e Remo, nacque la civiltà romana nel vii secolo a . c . e continuò la sua storia.'
        r=self.add('Origini',text);d=self.doc(r['id']);provider=self.s.provider(r['id'])
        with patch('wiki22.extended_reading.StudyEngine.open',return_value=dict(status='READY',paragraphs=[])):
            b=open_extended(provider,d['article_id'],sentence_iterator=documentary_sentences)
        self.assertEqual(len(b['paragraphs']),1);self.assertEqual(b['paragraphs'][0]['text'],text)
    def test_unicode_and_multiple_space_titles_remain_browsable(self):
        p=self.base/'titles.json';p.write_text(json.dumps([{'title':'Ａrte  italiana','text':'La raccolta documenta opere italiane.'}]))
        r=self.s.import_library(str(p),'Titoli');rows=self.s.search('Arte',mode='SINGLE',ids=[r['id']])['rows']
        self.assertEqual(rows[0]['title'],'Arte italiana');self.assertTrue(self.doc(r['id'])['notes'])
    def test_formats_report_actual_converter_presence(self):
        f=formats();self.assertIn('.epub',f['native']);self.assertEqual(next(x for x in f['optional'] if x['extension']=='.pdf')['available'],bool(shutil.which('pdftotext')))

if __name__=='__main__':unittest.main()
