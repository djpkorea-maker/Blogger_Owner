import tempfile
import unittest
from r3studio.google import Monitor,SearchConsole,index_grade
from r3studio.sync import Store
class Tests(unittest.TestCase):
 def test_invalid_cache_dates_force_refresh(self):
  for stamp in ('broken','2026-01-01T00:00:00','2999-01-01T00:00:00+00:00'):
   with self.subTest(stamp=stamp),tempfile.TemporaryDirectory() as d:
    s=Store(d+'/db');m=Monitor(s,lambda u:{'status':200,'url':u,'body':'','headers':{},'redirects':[]})
    m.check('b','1','https://example.com/p')
    s.db.execute('UPDATE google_status SET checked_at=?',(stamp,));s.db.execute('UPDATE crawl_documents SET checked_at=?',(stamp,));s.db.commit()
    result,reused=m.check('b','1','https://example.com/p')
    self.assertFalse(reused);self.assertEqual(result['technical_status'],'ACCESSIBLE');s.close()
 def test_corrupt_cache_payloads_force_refresh(self):
  for payload in ('bad-json','[]','null','{"public_crawl":{}}'):
   with self.subTest(payload=payload),tempfile.TemporaryDirectory() as d:
    s=Store(d+'/db');m=Monitor(s,lambda u:{'status':200,'url':u,'body':'','headers':{},'redirects':[]})
    m.check('b','1','https://example.com/p')
    s.db.execute('UPDATE google_status SET evidence=?',(payload,));s.db.execute('UPDATE crawl_documents SET payload=?',(payload,));s.db.commit()
    result,reused=m.check('b','1','https://example.com/p')
    self.assertFalse(reused);self.assertTrue(result['previous_record_unusable'])
    self.assertFalse(result['changed'])
    self.assertEqual(result['technical_status'],'ACCESSIBLE');s.close()
 def test_new_persistent_and_resolved_public_problem(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');body=['']
   m=Monitor(s,lambda u:{'status':200,'url':u,'body':body[0],'headers':{},'redirects':[]})
   first,_=m.check('b','1','https://example.com/p',0)
   self.assertTrue(first['first_check']);self.assertFalse(first['new_problem'])
   body[0]='<meta name="robots" content="noindex">'
   new,_=m.check('b','1','https://example.com/p',0)
   self.assertTrue(new['new_problem']);self.assertFalse(new['persistent_problem'])
   persistent,_=m.check('b','1','https://example.com/p',0)
   self.assertFalse(persistent['new_problem']);self.assertTrue(persistent['persistent_problem'])
   body[0]='';resolved,_=m.check('b','1','https://example.com/p',0)
   self.assertEqual(resolved['resolved_problems'],['public:NOINDEX'])
   self.assertFalse(resolved['needs_attention']);s.close()
 def test_google_priority_and_labels(self):
  from r3studio.presentation import google_sort_key,google_text
  rows=[{'title':'정상'},{'title':'기존 문제','needs_attention':True},{'title':'변경','changed':True},{'title':'새 문제','new_problem':True}]
  self.assertEqual([r['title'] for r in sorted(rows,key=google_sort_key)],['새 문제','변경','기존 문제','정상'])
  text=google_text({'technical_status':'NOINDEX','index_status':'확인 불가','new_problem':True,'first_check':False,'changed':True})
  self.assertIn('새로 발견한 문제',text);self.assertNotIn('첫 검사',text)
 def test_bad_console_response_preserves_public_observations(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');console=SearchConsole('private-token','https://example.com/',lambda p:{'inspectionResult':None})
   m=Monitor(s,lambda u:{'status':200,'url':u,'body':'<html></html>','headers':{},'redirects':[]},console)
   result,_=m.check('b','1','https://example.com/p')
   self.assertEqual(result['technical_status'],'ACCESSIBLE');self.assertEqual(result['index_status'],'확인 불가');self.assertTrue(result['needs_attention']);self.assertNotIn('private-token',str(result));s.close()
 def test_console_shape_errors_are_controlled(self):
  for response in ([],{}, {'inspectionResult':{'indexStatusResult':{'coverageState':None}}}):
   with self.assertRaises(ValueError):SearchConsole('key','site',lambda p:response).inspect('url')
 def test_preview_none_and_other_bot_do_not_block_google_index(self):
  from r3studio.google import blocks_index
  self.assertFalse(blocks_index('max-image-preview:none'))
  self.assertFalse(blocks_index('bingbot: noindex',header=True))
  self.assertTrue(blocks_index('googlebot: noindex',header=True))
 def test_changed_article_invalidates_monitor_cache(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');m=Monitor(s,lambda u:{'status':200,'url':u,'body':'','headers':{},'redirects':[]})
   m.check('b','1','https://example.com/p',post_fingerprint='old')
   self.assertTrue(m.check('b','1','https://example.com/p',post_fingerprint='old')[1])
   self.assertFalse(m.check('b','1','https://example.com/p',post_fingerprint='new')[1]);s.close()
 def test_http_error_not_hidden_by_canonical_warning(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');m=Monitor(s,lambda u:{'status':404,'url':u,'body':'<link rel="canonical" href="/a"><link rel="canonical" href="/b">','headers':{},'redirects':[]})
   r,_=m.check('b','1','https://example.com/p');self.assertEqual(r['technical_status'],'404');self.assertTrue(r['canonical_review']);s.close()
 def test_none_directive_means_noindex(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');m=Monitor(s,lambda u:{'status':200,'url':u,'body':'<meta name="robots" content="none">','headers':{},'redirects':[]})
   r,_=m.check('b','1','https://example.com/p');self.assertTrue(r['noindex']);self.assertTrue(r['needs_attention']);s.close()
 def test_public_not_indexed_claim(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');m=Monitor(s,lambda url:{'status':200,'url':url,'body':'<html></html>','headers':{},'redirects':[]})
   r,_=m.check('b','1','https://example.com/p')
   self.assertEqual(r['technical_status'],'ACCESSIBLE');self.assertEqual(r['index_status'],'확인 불가')
   self.assertTrue(m.check('b','1','https://example.com/p')[1]);s.close()
 def test_noindex_change(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');body=['<html></html>']
   m=Monitor(s,lambda url:{'status':200,'url':url,'body':body[0],'headers':{},'redirects':[]})
   m.check('b','1','https://example.com/p');body[0]='<meta name="robots" content="noindex">'
   r,_=m.check('b','1','https://example.com/p',0)
   self.assertEqual(r['technical_status'],'NOINDEX');self.assertTrue(r['changed']);s.close()
 def test_console_categories(self):
  self.assertEqual(index_grade({'verdict':'PASS'}),'색인됨')
  self.assertEqual(index_grade({'coverageState':'Crawled - currently not indexed'}),'크롤링됨-미색인')
  self.assertEqual(index_grade({'pageFetchState':'SOFT_404'}),'soft 404')
 def test_console_failure_preserves_public(self):
  class C:
   def inspect(self,url):raise ValueError('fail')
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');m=Monitor(s,lambda url:{'status':404,'url':url,'body':'','headers':{},'redirects':[]},C())
   r,_=m.check('b','1','https://example.com/p')
   self.assertEqual(r['technical_status'],'404');self.assertEqual(r['index_status'],'확인 불가');s.close()
if __name__=='__main__':unittest.main()
