import hashlib
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.request import Request,urlopen
from urllib.error import HTTPError
import zlib
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'wiki22/src'))
from wiki22.encyclopedia_service import EncyclopediaService
from wiki22.library_download import LibraryDownloads,Paused
from wiki22.source_probe import SourceProbe,public_address,fetch_source
from wiki22.encyclopedia_app import EncyclopediaHTTP

class RangeHandler(BaseHTTPRequestHandler):
    data=b'';requests=[];bad=False
    def log_message(self,*a):pass
    def do_GET(self):
        start,end=map(int,self.headers['Range'].removeprefix('bytes=').split('-'))
        type(self).requests.append((start,end))
        self.send_response(200 if self.bad else 206)
        self.send_header('Content-Range',f'bytes {start}-{end}/{len(self.data)}')
        self.end_headers();self.wfile.write(self.data[start:end+1])

class AcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name)
        self.s=EncyclopediaService(self.base/'profile')
        self.probe=SourceProbe(self.s)
        self.server=None
    def tearDown(self):
        if self.server:self.server.shutdown();self.server.server_close()
        self.probe.close();self.s.close();self.temp.cleanup()
    def catalog(self,raw=b'catalog fixture'):
        compressed=zlib.compress(raw)[2:-4]
        RangeHandler.data=compressed;RangeHandler.requests=[];RangeHandler.bad=False
        self.server=ThreadingHTTPServer(('127.0.0.1',0),RangeHandler)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        return dict(id='sample',name='Sample',description='fixture',license='test',library=dict(id='sample',name='Sample',enabled=True,article_count=1),url=f'http://127.0.0.1:{self.server.server_port}/data',archive_bytes=len(compressed),pack='pack.json',files=[dict(path='pack.json',offset=0,compressed=len(compressed),bytes=len(raw),method=8,sha256=hashlib.sha256(raw).hexdigest())])
    def test_empty_profile(self):
        self.assertEqual(self.s.libraries(),[]);self.assertTrue(self.s.registry.path.exists())
    def test_download_validates_and_registers(self):
        c=self.catalog();d=LibraryDownloads(self.s,[c]);d.install(c)
        self.assertEqual(self.s.registry.resolve_pack('sample').read_bytes(),b'catalog fixture')
    def test_resume_existing_partial(self):
        c=self.catalog();d=LibraryDownloads(self.s,[c]);p=d.base/'sample';p.mkdir();(p/'pack.json.download').write_bytes(RangeHandler.data[:5]);d.install(c)
        self.assertEqual(RangeHandler.requests[0][0],5)
    def test_server_ignores_range(self):
        c=self.catalog();RangeHandler.bad=True;d=LibraryDownloads(self.s,[c])
        with self.assertRaises(ValueError):d.install(c)
        self.assertEqual(self.s.libraries(),[])
    def test_bad_hash_not_registered(self):
        c=self.catalog();c['files'][0]['sha256']='0'*64;d=LibraryDownloads(self.s,[c])
        with self.assertRaisesRegex(ValueError,'SHA-256'):d.install(c)
        self.assertEqual(self.s.libraries(),[])
        self.assertFalse((d.base/'sample/pack.json.download').exists())
    def test_pause_then_resume(self):
        c=self.catalog();d=LibraryDownloads(self.s,[c]);d.stop.set()
        with self.assertRaises(Paused):d.install(c)
        d.stop.clear();d.install(c);self.assertEqual(len(self.s.libraries()),1)
    def test_disk_space(self):
        c=self.catalog();d=LibraryDownloads(self.s,[c])
        with patch('wiki22.library_download.shutil.disk_usage') as usage:
            usage.return_value.free=0
            with self.assertRaisesRegex(ValueError,'Spazio'):d.install(c)
        self.assertEqual(RangeHandler.requests,[])
    def test_recovery_after_rename(self):
        c=self.catalog();d=LibraryDownloads(self.s,[c]);d.install(c);self.s.registry.save(self.s.registry.empty());d.install(c);self.assertEqual(len(self.s.libraries()),1)
    def test_local_preview_selection_reading(self):
        folder=self.base/'sources';folder.mkdir()
        a=folder/'giardino.txt';a.write_text('# Giardino\nIl giardino ospita alberi e fiori. La biblioteca conserva documenti sulla storia del giardino e delle piante.\n'*4)
        (folder/'altro.txt').write_text('Una fonte non selezionata parla di astronomia. '*10)
        (folder/'secret.bin').write_bytes(b'bin')
        before=a.read_bytes();preview=self.probe.scan(paths=[str(folder)])
        row=next(r for r in preview['rows'] if r['label']=='giardino.txt')
        result=self.probe.create(preview['token'],[row['id']],'Giardini')
        self.assertEqual(result['articles'],1);self.assertEqual(a.read_bytes(),before)
        found=self.s.search('Giardino')['rows'];self.assertEqual(len(found),1)
        article=self.s.article(library_id=found[0]['library_id'],article_id=found[0]['article_id'])
        self.assertIn('file:',article['notes'][0]['source'])
    def test_changed_source_requires_new_preview(self):
        p=self.base/'sample.txt';p.write_text('Originale '*30);preview=self.probe.scan(paths=[str(p)]);p.write_text('Modificato '*40)
        with self.assertRaisesRegex(ValueError,'cambiata'):self.probe.create(preview['token'],['0'],'Prova')
    def test_web_provenance(self):
        with patch('wiki22.source_probe.fetch_source',return_value=dict(url='https://example.org/source',raw=b'<h1>Science</h1><p>Science studies nature and creates knowledge based on observation and careful experiments.</p>',extension='.html')):
            p=self.probe.scan(urls=['https://example.org/source'])
        result=self.probe.create(p['token'],['0'],'Web');self.assertEqual(result['articles'],1)
        provider=self.s.provider(result['id']);rows=provider.browse_titles();book=provider.documentary_book(rows[0]['article_id'])
        self.assertIn('https://example.org/source',json.dumps(book))
    def test_private_destinations(self):
        for address in ('127.0.0.1','10.0.0.1','169.254.169.254','::1','192.168.1.1'):
            with self.assertRaises(ValueError):public_address('http://['+address+']/' if ':' in address else 'http://'+address+'/')
    def test_credentials_and_ports(self):
        for url in ('file:///etc/passwd','https://user:pass@example.com/','http://example.com:8000/'):
            with self.assertRaises(ValueError):public_address(url)
    def test_robots_denial(self):
        with patch('wiki22.source_probe.public_address',return_value=(__import__('urllib.parse',fromlist=['urlsplit']).urlsplit('https://example.org/'), '93.184.215.14',443)),patch('wiki22.source_probe.fetch_public',return_value=dict(status=200,raw=b'User-agent: *\nDisallow: /',url='https://example.org/robots.txt')) as fetch:
            with self.assertRaisesRegex(ValueError,'robots'):fetch_source('https://example.org/')
            self.assertEqual(fetch.call_count,1)
    @unittest.skipIf(sys.platform=='win32','Creating symlinks requires elevated Windows privileges')
    def test_symlinks_skipped(self):
        p=self.base/'x.txt';p.write_text('sample');link=self.base/'link.txt';link.symlink_to(p)
        with self.assertRaises(ValueError):self.probe.scan(paths=[str(link)])
    def test_api_requires_token_and_can_start_empty(self):
        server=EncyclopediaHTTP(('127.0.0.1',0),self.s)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        base=f'http://127.0.0.1:{server.server_port}'
        try:
            req=Request(base+'/api/probe/scan',data=b'{}',headers={'Content-Type':'application/json'})
            with self.assertRaises(HTTPError) as error:urlopen(req)
            self.assertEqual(error.exception.code,403)
            req=Request(base+'/api/catalog',data=b'{}',headers={'Content-Type':'application/json','X-Wiki22-Token':server.token})
            self.assertEqual(len(json.load(urlopen(req))['items']),1)
        finally:server.shutdown();server.server_close()

if __name__=='__main__':unittest.main()
