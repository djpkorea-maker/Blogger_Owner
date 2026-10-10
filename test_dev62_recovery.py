import copy
import io
import json
import tempfile
import unittest
import urllib.error
from unittest.mock import patch
from r3studio.bridge import BridgeAdapter,BridgeError
from r3studio.evidence import Research,EvidenceHold
from r3studio.sync import Store,Sync
from r3studio.existing import partial_link_review,record_incomplete
from r3studio.links import inspect_link_access
from r3studio.presentation import inspection_text,history_text
from r3studio.tasks import TaskLog,finish_error,Cancelled
from test_generation import pack
from test_sync import Adapter

class ResearchAI:
 model='test'
 def __init__(self,mode='repair'):
  self.mode=mode;self.searches=0;self.formats=0;self.prompts=[]
 def ask(self,prompt,**kw):
  self.searches+=1;self.prompts.append(prompt)
  return {'citations':[] if self.mode=='empty' else [{'url':s['url']} for s in pack()['sources']]}
 def object(self,prompt):
  self.formats+=1;self.prompts.append(prompt);p=pack()
  for f in p['facts']:f['article_excerpt']='電波の減衰 条件に注意'
  if self.mode=='mismatch' or self.mode=='repair' and self.formats==1:p['sources'][0]['url']='https://wrong.example/manual?token=secret'
  if self.mode=='fragment':p['sources'][0]['url']+='#section'
  if self.mode=='short':
   p['sources']=p['sources'][:1]
   p['claim_checks']=[{'text':'본문의 핵심 주장','status':'UNVERIFIED','reason':'공식 조건 자료 미확보'}]
  return p

class Tests(unittest.TestCase):
 def test_bridge_diagnostics_distinguish_failures_and_keep_secrets_out(self):
  errors=[(TimeoutError(),'TIMEOUT'),(urllib.error.URLError(TimeoutError()),'TIMEOUT'),(urllib.error.URLError('secret'),'NETWORK'),(urllib.error.HTTPError('https://x?key=secret',403,'secret',{},io.BytesIO(b'secret')),'HTTP_ERROR')]
  for error,reason in errors:
   a=BridgeAdapter('https://script.google.com/macros/s/test/exec','secret','blog')
   with patch('urllib.request.urlopen',side_effect=error):
    with self.assertRaises(BridgeError) as caught:a.get_post('1')
   self.assertEqual(caught.exception.diagnostic['reason'],reason)
   self.assertNotIn('secret',json.dumps(caught.exception.diagnostic))
 def test_bridge_html_response_is_not_permission_diagnosis(self):
  a=BridgeAdapter('https://script.google.com/macros/s/test/exec','secret','blog')
  class Response:
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def read(self,*args):return b'<html>login</html>'
  with patch('urllib.request.urlopen',return_value=Response()):
   with self.assertRaises(BridgeError) as caught:a.get_post('1')
  self.assertEqual(caught.exception.diagnostic['reason'],'INVALID_JSON')
 def test_selected_refresh_rereads_target_and_changed_peers(self):
  s=Store(':memory:');a=Adapter();Sync(s,a,'blog').run();a.gets=0
  a.posts['1']['updated']='changed'
  result=Sync(s,a,'blog',refresh_ids=['0']).run()
  self.assertEqual(a.gets,2);self.assertEqual(result['reused'],1);s.close()
 def test_research_uses_body_and_existing_links_and_repairs_url(self):
  ai=ResearchAI();result=Research(ai).collect('title','topic',article='<p>電波の減衰 条件に注意</p><a href="https://manual.example/a">manual</a>')
  self.assertEqual(ai.searches,1);self.assertEqual(ai.formats,2)
  self.assertIn('電波の減衰',ai.prompts[0]);self.assertIn('https://manual.example/a',ai.prompts[0])
  self.assertEqual(result['sources'][0]['url'],pack()['sources'][0]['url'])
 def test_url_mismatch_failure_has_both_lists_and_is_bounded(self):
  ai=ResearchAI('mismatch')
  with self.assertRaises(EvidenceHold) as caught:Research(ai).collect('t','t',article='<p>검증 문장</p>')
  d=caught.exception.diagnostic
  self.assertEqual(ai.formats,3);self.assertEqual(ai.searches,1)
  self.assertTrue(d['search_urls']);self.assertEqual(d['unmatched_urls'],['https://wrong.example/manual'])
  self.assertNotIn('secret',json.dumps(d));self.assertIn('검증 문장',d['verification_targets'])
 def test_fragment_only_maps_to_real_search_source(self):
  result=Research(ResearchAI('fragment')).collect('t','t')
  self.assertEqual(result['sources'][0]['url'],pack()['sources'][0]['url'])
 def test_missing_search_sources_retries_at_most_twice(self):
  ai=ResearchAI('empty')
  with self.assertRaises(EvidenceHold):Research(ai).collect('t','t')
  self.assertEqual(ai.searches,3);self.assertEqual(ai.formats,0)
 def test_missing_claim_and_criteria_are_saved_and_shown(self):
  ai=ResearchAI('short')
  with self.assertRaises(EvidenceHold) as caught:Research(ai).collect('t','t')
  s=Store(':memory:');task=TaskLog(s,'심층 검사');finish_error(task,caught.exception)
  text=history_text(list(s.db.execute('SELECT * FROM task_runs')))
  self.assertIn('본문의 핵심 주장',text);self.assertIn('공식 조건 자료 미확보',text);self.assertIn('독립 A/B 출처',text);s.close()
 def test_partial_link_failure_does_not_hide_other_links_or_claim_pass(self):
  def fetch(url):
   if url.endswith('/bad'):raise TimeoutError()
   return {'status':200,'url':url}
  result=inspect_link_access('<a href="https://e.test/bad">bad</a><a href="https://e.test/good">good</a>','https://e.test',fetch)
  self.assertEqual([r['state'] for r in result['results']],['FETCH_FAILED','ACCESSIBLE'])
  self.assertFalse(result['factual_support_verified'])
 def test_research_failure_saves_partial_checks_and_stays_incomplete(self):
  s=Store(':memory:');a=Adapter();a.blog_id='blog';a.posts['0']['content']='<p>본문</p><a href="https://example.test/link">link</a>';Sync(s,a,'blog').run()
  with patch('r3studio.existing.public_fetch',return_value={'status':404,'url':'https://example.test/link'}):result=partial_link_review(s,a,'0')
  record=record_incomplete(s,'blog','0',EvidenceHold('근거 부족'),result)
  text=inspection_text({'post_id':'0','grade':record['grade'],'details':record})
  self.assertFalse(record['verified']);self.assertIn('404',text);self.assertIn('근거 적합성은 미검증',text);s.close()
 def test_desktop_failed_research_preserves_link_checks_and_limits_body_reads(self):
  import queue
  from pathlib import Path
  from types import SimpleNamespace
  from r3studio.app import App
  from r3studio.tasks import Cancellation
  with tempfile.TemporaryDirectory() as directory:
   a=Adapter();a.blog_id='blog';a.posts['0']['content']='<p>본문</p><a href="https://example.test/link">link</a>'
   s=Store(directory+'/studio.sqlite3');Sync(s,a,'blog').run();s.close();a.gets=0
   app=App.__new__(App);app.base=Path(directory);app.events=queue.Queue();app.cancel_token=Cancellation()
   ai=SimpleNamespace(transport=lambda request:{},model='test')
   with patch('r3studio.readiness.require_settings'),patch('r3studio.bridge.BridgeAdapter.from_environment',return_value=a),patch('r3studio.ai.Gemini.from_environment',return_value=ai),patch('r3studio.evidence.collect_cached',side_effect=EvidenceHold('근거 부족')),patch('r3studio.existing.public_fetch',return_value={'status':200,'url':'https://example.test/link'}):
    app.ai_worker('deep','0')
   self.assertEqual(a.gets,3) # selected refresh, partial before, partial after; no other body reads
   s=Store(directory+'/studio.sqlite3');row=s.db.execute('SELECT details FROM recovery_checks WHERE engine_version="R3.0-existing-incomplete" ORDER BY id DESC').fetchone()
   detail=json.loads(row[0]);self.assertEqual(detail['link_access']['results'][0]['state'],'ACCESSIBLE');self.assertFalse(detail['verified'])
   task=s.db.execute('SELECT status,details FROM task_runs ORDER BY id DESC').fetchone();self.assertEqual(task['status'],'FAILED');self.assertEqual(json.loads(task['details'])['reason'],'EVIDENCE_INCOMPLETE');s.close()
 def test_unavailable_originals_name_unverified_facts_and_urls(self):
  from r3studio.sources import verify_origins
  class Reader:
   def read(self,url):return {'status':'UNAVAILABLE','reason':'원문 접근 확인 불가'}
  with self.assertRaises(EvidenceHold) as caught:verify_origins(None,pack(),Reader())
  d=caught.exception.diagnostic
  self.assertEqual(len(d['unverified_claims']),len(pack()['facts']))
  self.assertEqual(d['unverified_claims'][0]['text'],pack()['facts'][0]['text'])
  self.assertEqual(d['source_checks'][0]['state'],'UNAVAILABLE')
 def test_partial_access_respects_cancellation(self):
  with self.assertRaises(Cancelled):inspect_link_access('<a href="https://e.test">a</a>','',checkpoint=lambda:(_ for _ in ()).throw(Cancelled()))
if __name__=='__main__':unittest.main()
