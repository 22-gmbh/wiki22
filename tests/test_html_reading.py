import tempfile
import unittest
from pathlib import Path

from wiki22.html_document import html_sections
from wiki22.encyclopedia_service import EncyclopediaService


class HTMLReadingTests(unittest.TestCase):
    def test_main_headings_paragraphs_and_inline_fidelity(self):
        raw = '''<header>Menu generale</header><main><div class="breadcrumb">Home</div><h1>Il<br>giardino</h1>
        <p>Un <strong>piccolo</strong> giardino.</p><p>Acqua &amp; luce.</p>
        <nav>Acquista</nav><h2><span>Cura</span><span>quotidiana</span></h2><p>Osserva le foglie.</p>
        <div hidden>Segreto</div><svg><text>Grafica</text></svg></main>
        <footer>Contatti</footer><script>non eseguire</script>'''
        self.assertEqual(html_sections(raw), [('Il giardino', 'Un piccolo giardino.\n\nAcqua & luce.'),
                                              ('Cura quotidiana', 'Osserva le foglie.')])

    def test_article_fallback_and_plain_fragment(self):
        self.assertEqual(html_sections('<div>Menu</div><article><h2>Titolo</h2><p>Uno.</p><p>Due.</p></article>'),
                         [('Titolo', 'Uno.\n\nDue.')])
        self.assertEqual(html_sections('<p>A <em>B</em> C.</p><p>D.</p>'), [('Documento', 'A B C.\n\nD.')])

    def test_import_to_reading_preserves_blocks_and_source_notes(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            source = base / 'giardino.html'
            source.write_text('<main><h1>Giardino</h1><p>La rosa cresce.</p><p>La menta profuma.</p>'
                              '<h2>Acqua</h2><p>Il terreno resta umido.</p>'
                              '<h2>Giardino</h2><p>Ultimo paragrafo.</p></main>', encoding='utf-8')
            with_source = source.read_bytes()
            service = EncyclopediaService(base / 'app')
            try:
                service.import_library(str(source), 'Giardino')
                row = service.search('', mode='SINGLE', ids=['giardino'])['rows'][0]
                document = service.article('giardino', row['article_id'], mode='SINGLE', ids=['giardino'])
                blocks = [block for page in document['pages'] for block in page]
                self.assertEqual([b['heading'] for b in blocks], ['Giardino', 'Giardino', 'Acqua', 'Giardino'])
                self.assertEqual([b['sentences'][0]['text'] for b in blocks],
                                 ['La rosa cresce.', 'La menta profuma.', 'Il terreno resta umido.', 'Ultimo paragrafo.'])
                self.assertIn('La menta profuma.', document['notes'][0]['context'])
                self.assertEqual(source.read_bytes(), with_source)
            finally:
                service.close()


if __name__ == '__main__':
    unittest.main()
