import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from r3studio.evidence import Research,EvidenceHold,validate_pack
from r3studio.source_urls import resolve_pack,resolve
from r3studio.images import inspect_existing_images
from r3studio.captions import replace_image_text,image_captions
from r3studio.sync import Store,post_hash
from r3studio.progress import progress_state
from r3studio.start_mode import auto_start_enabled
from r3studio.links import check_links,LinkHold
from r3studio.recovery import Recovery,RecoveryHold
from r3studio.gates import Document,Result
from test_generation import pack
from test_images import image
from test_public_images import CONTENT

class Pixels:
 model='test'
 def __init__(self,fail_first=False):self.calls=0;self.fail_first=fail_first
 def image_object(self,prompt,data,mime):
  self.calls+=1
  review={'relevant':True,'visual_quality':True,'single_scene':True,'no_overlay_text':True,'safe_depiction':True,'alt_match':False,'caption_match':False,'observed':'작업대에 놓인 가전제품','alt':'작업대 위에 놓인 가전제품','caption':'작업대 위에 가전제품과 주변 공간이 보입니다.'}
  if self.fail_first and self.calls==1:review['relevant']=False
  return review

class Tests(unittest.TestCase):
 def test_two_relay_sources_count_real_destination_domains(self):
  p=pack()
  for i,s in enumerate(p['sources']):s['url']='https://vertexaisearch.cloud.google.com/grounding-api-redirect/'+str(i)
  resolved=resolve_pack(p,lambda u:'https://manufacturer.example/manual' if u.endswith('/0') else 'https://agency.example/guide')
  validate_pack(resolved)
  self.assertEqual(len(resolved['source_url_mappings']),2)
 def test_same_destination_never_becomes_two_independent_sources(self):
  p=pack();resolve_pack(p,lambda u:'https://same.example/manual')
  with self.assertRaises(EvidenceHold):validate_pack(p)
 def test_unresolved_relay_never_passes(self):
  p=pack();p['sources'][0]['url']='https://vertexaisearch.cloud.google.com/grounding-api-redirect/x'
  with self.assertRaises(EvidenceHold):resolve_pack(p,lambda u:u)
 def test_research_resolves_before_model_ledger_and_preserves_mapping(self):
  class AI:
   def ask(self,*a,**kw):return {'text':'source','citations':[{'url':'https://vertexaisearch.cloud.google.com/grounding-api-redirect/0'},{'url':'https://vertexaisearch.cloud.google.com/grounding-api-redirect/1'}]}
   def object(self,prompt):
    self.prompt=prompt;return pack()
  ai=AI()
  with patch('r3studio.source_urls.resolve',side_effect=lambda u:pack()['sources'][int(u[-1])]['url']):result=Research(ai).collect('title','topic')
  self.assertIn('https://manufacturer.example/manual',ai.prompt)
  self.assertTrue(any('grounding-api-redirect' in m['search_url'] for m in result['source_url_mappings']))
 def test_resolver_head_failure_is_controlled(self):
  with patch('urllib.request.build_opener') as opener:
   opener.return_value.open.side_effect=TimeoutError()
   with self.assertRaises(EvidenceHold):resolve('https://vertexaisearch.cloud.google.com/grounding-api-redirect/x')
 def test_images_are_all_checked_when_first_needs_replacement(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');ai=Pixels(True)
   review=inspect_existing_images(s,ai,'title',CONTENT,d,'blog','1',lambda u:image())
   self.assertEqual(ai.calls,2);self.assertEqual(len(review['items']),2)
   self.assertTrue(review['items'][0]['replacement_needed']);self.assertIn('suggested_text',review['items'][1]);self.assertFalse(review['all_pass']);s.close()
 def test_missing_alt_still_reaches_pixels_and_produces_suggestion(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');ai=Pixels();review=inspect_existing_images(s,ai,'title',CONTENT.replace('alt="전자레인지"','alt=""'),d,'blog','1',lambda u:image())
   self.assertEqual(ai.calls,2);self.assertIn('ALT 누락',review['items'][0]['issues']);self.assertIn('suggested_text',review['items'][0]);s.close()
 def test_pixel_text_edits_preserve_image_sources_and_bind_captions(self):
  suggestions=[{'index':1,'url':Document(CONTENT).images[0]['src'],'suggested_text':{'alt':'수정된 실제 이미지 설명','caption':'실제 픽셀에서 보이는 가전제품의 모습입니다.'}}]
  edited=replace_image_text(CONTENT,suggestions)
  self.assertEqual([i['src'] for i in Document(edited).images],[i['src'] for i in Document(CONTENT).images])
  self.assertEqual(Document(edited).images[0]['alt'],suggestions[0]['suggested_text']['alt']);self.assertEqual(image_captions(edited)[0],suggestions[0]['suggested_text']['caption'])
 def test_ambiguous_caption_edit_is_blocked(self):
  content='<p><img src="https://lh3.googleusercontent.com/a" alt="old"></p>'
  with self.assertRaises(Exception):replace_image_text(content,[{'index':1,'url':'https://lh3.googleusercontent.com/a','suggested_text':{'alt':'new','caption':'description'}}])
 def test_existing_relay_link_is_checked_against_verified_final_source(self):
  own='https://blog.example/post';peer={'status':'LIVE','url':'https://blog.example/related'}
  content='<a href="https://blog.example/related">related</a><a href="https://relay.example/source">source</a>'
  def fetch(u):return {'status':200,'url':'https://manufacturer.example/manual' if 'relay.example' in u else u}
  self.assertTrue(check_links(content,own,[peer],pack(),fetch)['pass'])
  with self.assertRaises(LinkHold):check_links(content,own,[peer],pack(),lambda u:{'status':200,'url':'https://unknown.example' if 'relay' in u else u})
 def test_waiting_progress_has_no_fabricated_percentage(self):
  state=progress_state('근거 조사 · AI 응답 대기 중')
  self.assertEqual(state['mode'],'indeterminate');self.assertTrue(state['waiting']);self.assertIn('완료율 확인 불가',state['label'])
  self.assertEqual(progress_state('Blogger 조회 5/10')['current'],5)
 def test_auto_sync_is_opt_in(self):
  self.assertFalse(auto_start_enabled({}));self.assertFalse(auto_start_enabled({'R3_AUTO_SYNC':'0'}));self.assertTrue(auto_start_enabled({'R3_AUTO_SYNC':'1'}))
 def test_repair_keeps_body_preview_when_image_replacement_blocks_apply(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');before={'id':'1','status':'LIVE','title':'title','content':CONTENT+'<a href="https://blog.example/related">related</a>','url':'https://blog.example/post','updated':'v1'}
   adapter=SimpleNamespace(blog_id='blog',get_post=lambda pid:dict(before))
   ai=SimpleNamespace(object=lambda prompt:{'content_html':before['content']+'<p>근거에 따른 수정 문장</p>','changes':['조건 추가']})
   with patch('r3studio.recovery.collect_cached',return_value=pack()),patch('r3studio.recovery.inspect_existing_images',return_value={'items':[{'replacement_needed':True}]}):result=Recovery(s,ai,adapter).propose('1',d)
   self.assertEqual(result['status'],'HOLD');self.assertIn('근거에 따른 수정 문장',result['proposed_content'])
   with self.assertRaises(RecoveryHold):Recovery(s,ai,adapter).apply_proposal(result['proposal_id'])
   s.close()
 def test_repair_alt_edit_is_revalidated_before_pass_without_writing(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');before={'id':'1','status':'LIVE','title':'title','content':CONTENT+'<a href="https://blog.example/related">related</a>','url':'https://blog.example/post','updated':'v1'}
   adapter=SimpleNamespace(blog_id='blog',get_post=lambda pid:dict(before))
   ai=SimpleNamespace(object=lambda prompt:{'content_html':before['content'],'changes':['조건 보완']},ask=lambda *a,**k:{'citations':[{'url':'https://manufacturer.example/manual'}]})
   item={'index':1,'url':Document(CONTENT).images[0]['src'],'issues':['ALT 불일치'],'replacement_needed':False,'suggested_text':{'alt':'픽셀에 맞게 수정한 설명','caption':'실제 픽셀에 보이는 장면의 설명입니다.'}}
   def prepare(pid,title,content,labels):return {'expected_hash':post_hash(before),'expected_updated':'v1','proposal':{'title':title,'content':content,'labels':labels}}
   with patch('r3studio.recovery.collect_cached',return_value=pack()),patch('r3studio.recovery.inspect_existing_images',return_value={'items':[item]}),patch('r3studio.recovery.fast_check',return_value=Result('NEEDS_DEEP','DEEP',[],{})),patch('r3studio.recovery.evaluate',return_value={'text_verified':True}),patch('r3studio.recovery.check_public_images',return_value=[{},{}]) as final_pixels,patch('r3studio.recovery.check_links',return_value={'pass':True}),patch('r3studio.recovery.Apply.prepare',side_effect=prepare):
    result=Recovery(s,ai,adapter).propose('1',d)
   self.assertEqual(result['status'],'PASS');self.assertIn('픽셀에 맞게 수정한 설명',final_pixels.call_args.args[3]);self.assertIn('image_text_changes',result);s.close()
if __name__=='__main__':unittest.main()
