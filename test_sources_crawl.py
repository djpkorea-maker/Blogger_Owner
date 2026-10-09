import tempfile
import unittest
from r3studio.sync import Store,digest
from r3studio.sources import SourceReader,verify_origins,require_originals
from r3studio.evidence import EvidenceHold
from r3studio.crawl import robots_rules,CrawlInspector
from test_generation import pack
class ClaimAI:
 def object(self,prompt):
  return {'sources':[{'source_id':'s1','grade':'A','publisher':'제조사1'},{'source_id':'s2','grade':'A','publisher':'기관2'}],'claims':[{'fact_id':str(i),'source_id':'s1' if i%2 else 's2','quote':'원문에서 확인 가능한 안전 조건과 사용 지침입니다.','supported':True} for i in range(4)]}
class Tests(unittest.TestCase):
 def test_missing_claim_records_do_not_count_as_verification(self):
  p=pack();p['original_verification'].pop('claims')
  with self.assertRaises(EvidenceHold):require_originals(p)
 def test_changed_original_text_invalidates_verification(self):
  p=pack();p['original_verification']['originals']['s1']['text']='변경된 원문'
  with self.assertRaises(EvidenceHold):require_originals(p)
 def test_invented_stored_quote_invalidates_verification(self):
  p=pack();p['original_verification']['claims'][0]['quote']='원문에는 존재하지 않는 임의의 구절입니다.'
  with self.assertRaises(EvidenceHold):require_originals(p)
 def test_inline_markup_preserves_visible_words(self):
  from r3studio.sources import Extract,norm
  self.assertEqual(norm(''.join(Extract('<p>전기<strong>안전</strong></p><p>조건</p>').text)),'전기안전 조건')
 def test_real_quote_required(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');reader=SourceReader(s,lambda u:{'status':200,'url':u,'headers':{'Content-Type':'text/html'},'body':'<p>'+('원문에서 확인 가능한 안전 조건과 사용 지침입니다. '*8)+'</p>'})
   p=verify_origins(ClaimAI(),pack(),reader);require_originals(p)
   self.assertEqual(len(p['original_verification']['claims']),4)
   p['facts'][0]['text']='근거 변경'
   with self.assertRaises(EvidenceHold):require_originals(p)
   s.close()
 def test_invented_quote_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');reader=SourceReader(s,lambda u:{'status':200,'url':u,'headers':{'Content-Type':'text/html'},'body':'<p>'+('다른 문서의 다른 문장입니다. '*20)+'</p>'})
   with self.assertRaises(EvidenceHold):verify_origins(ClaimAI(),pack(),reader)
   s.close()
 def test_longest_allow_and_googlebot_group(self):
  rules='User-agent: *\nDisallow: /\nUser-agent: Googlebot\nDisallow: /private\nAllow: /private/public\n'
  self.assertEqual(robots_rules(rules,'https://example.com/private/public')['state'],'ALLOWED')
  self.assertEqual(robots_rules(rules,'https://example.com/private/secret')['state'],'BLOCKED')
 def test_sitemap_index(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');url='https://example.com/post'
   def fetch(u):
    body='User-agent: *\nSitemap: https://example.com/map.xml' if u.endswith('robots.txt') else '<sitemapindex><sitemap><loc>https://example.com/part.xml</loc></sitemap></sitemapindex>' if u.endswith('map.xml') else '<urlset><url><loc>'+url+'</loc></url></urlset>'
    return {'status':200,'url':u,'body':body,'headers':{}}
   r=CrawlInspector(s,fetch).inspect(url);self.assertEqual(r['sitemap_state'],'FOUND');self.assertEqual(r['robots_state'],'ALLOWED');s.close()
 def test_empty_directive_starts_separate_group(self):
  rules='User-agent: Googlebot\nDisallow:\nUser-agent: *\nDisallow: /\n'
  self.assertEqual(robots_rules(rules,'https://example.com/post')['state'],'ALLOWED')
if __name__=='__main__':unittest.main()
