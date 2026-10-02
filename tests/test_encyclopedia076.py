import json,tempfile,unittest
from pathlib import Path
from wiki22.encyclopedia_service import EncyclopediaService
from wiki22.encyclopedia_management import manage,place_readings
from wiki22.encyclopedia_context import calendar_mentions

class ManagementTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.s=EncyclopediaService(self.root/'profile');self.addCleanup(self.s.close)
  self.libs=[]
  for name in ['A','B']:
   f=self.root/(name+'.json');f.write_text(json.dumps([{'title':t,'text':text} for t,text in [('Roma','Roma è una città. La storia di Roma comprende diverse epoche.'),('Storia di Roma','La storia di Roma comprende diverse epoche e numerosi monumenti.'),('Storia di Romagna','La Romagna ha una storia distinta.'),('Roma (Australia)','Roma è una città australiana.'),('1983','# Settembre\n\n* 1o settembre – primo evento.\n* 26 settembre – secondo evento.\n* 27 settembre – terzo evento.')]]));self.libs.append(self.s.import_library(str(f),name)['id'])
 def row(self):return self.s.search('Roma',mode='SINGLE',ids=[self.libs[0]])['rows'][0]
 def test_remove_restore_preserves_pack_and_shelf(self):
  r=self.row();d=self.s.article(r['library_id'],r['article_id']);self.s.bookmark(r['library_id'],r['article_id'],mode='SINGLE',ids=[self.libs[0]],source_hash=d['source_hash']);before=self.s.shelf();p=self.s.registry.resolve_pack(self.libs[0]);data=p.read_bytes()
  self.s.save_preferences(dict(mode='SINGLE',ids=[self.libs[0]]));manage(self.s,self.libs[0],'remove')
  self.assertEqual(self.s.preferences()['mode'],'CUSTOM');self.assertEqual(self.s.preferences()['ids'],[]);self.assertEqual(p.read_bytes(),data);self.assertEqual(self.s.shelf(),before)
  self.assertTrue(next(x for x in self.s.libraries() if x['id']==self.libs[0])['removed']);self.assertTrue(all(x['library_id']==self.libs[1] for x in self.s.search('Roma')['rows']))
  with self.assertRaises(ValueError):self.s.article(r['library_id'],r['article_id'])
  manage(self.s,self.libs[0],'restore');self.assertEqual(self.s.article(r['library_id'],r['article_id'])['source_hash'],d['source_hash']);self.assertEqual(self.s.shelf(),before)
 def test_rename_validation_and_persistence(self):
  manage(self.s,self.libs[0],'rename','Nuovo nome');self.assertEqual(self.row()['library_name'],'Nuovo nome')
  for name in ['',None,'a'*81,'line\nbreak']:
   with self.assertRaises(ValueError):manage(self.s,self.libs[0],'rename',name)
  other=EncyclopediaService(self.root/'profile')
  try:self.assertEqual(other.registry.get(self.libs[0])['name'],'Nuovo nome')
  finally:other.close()
 def test_remove_all_idempotent_and_restore_missing_file(self):
  for lib in self.libs:manage(self.s,lib,'remove');manage(self.s,lib,'remove')
  self.assertFalse(any(x['enabled'] for x in self.s.libraries()))
  p=self.s.registry.resolve_pack(self.libs[0]);p.rename(p.with_suffix('.held'))
  with self.assertRaises(ValueError):manage(self.s,self.libs[0],'restore')
  self.assertTrue(self.s.registry.get(self.libs[0])['removed'])
 def test_invalid_operation_does_not_mutate(self):
  before=self.s.registry.load()
  for id,act in [('unknown','remove'),(self.libs[0],'delete')]:
   with self.assertRaises(ValueError):manage(self.s,id,act)
  self.assertEqual(before,self.s.registry.load())
 def test_places_scope_boundary_and_composition(self):
  r=self.row();p=place_readings(self.s,r['library_id'],r['article_id'],mode='SINGLE',ids=[self.libs[0]])
  self.assertEqual([x['title'] for x in p['rows']],['Roma','Storia di Roma']);self.assertTrue(all(x['library_id']==self.libs[0] for x in p['rows']))
  result=self.s.research([{k:x[k] for k in ['library_id','article_id']} for x in p['rows']],mode='SINGLE',ids=[self.libs[0]])
  self.assertTrue(result['pages']);self.assertEqual(len(result['documents']),2)
  with self.assertRaises(ValueError):place_readings(self.s,r['library_id'],r['article_id'],mode='SINGLE',ids=[self.libs[1]])
  self.assertEqual(len(place_readings(self.s,r['library_id'],r['article_id'])['rows']),4)
 def test_homonymous_places_do_not_share_title_themes(self):
  r=next(x for x in self.s.search('Roma (Australia)')['rows'] if x['library_id']==self.libs[0])
  p=place_readings(self.s,r['library_id'],r['article_id'],mode='SINGLE',ids=[self.libs[0]])
  self.assertEqual([x['title'] for x in p['rows']],['Roma (Australia)'])
 def test_empty_date_nearby_keeps_precision_and_source(self):
  t=self.s.timeline_date(1983,9,22,mode='SINGLE',ids=[self.libs[0]])
  self.assertEqual(t['events'],[]);self.assertEqual([e['date']['day'] for e in t['nearby']['events']],[1,26,27]);self.assertEqual(t['date_filter']['day'],22)
  self.assertEqual(len(self.s.timeline_date(1983,9,1,mode='SINGLE',ids=[self.libs[0]])['events']),1)
 def test_ordinal_calendar_dates(self):
  for suffix in ['o','º','°','']:
   dates=calendar_mentions(dict(heading='Settembre',excerpt=f'* 1{suffix} settembre – evento.'),'1983');self.assertEqual(dates[0]['day'],1)

if __name__=='__main__':unittest.main()
