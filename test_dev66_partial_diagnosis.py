import copy,json,tempfile,unittest
from unittest.mock import patch
from r3studio.sources import verify_origins,require_originals
from r3studio.evidence import EvidenceHold,collect_cached
from r3studio.deep import diagnose_incomplete,evaluate
from r3studio.sync import Store,Sync
from r3studio.existing import inspect_existing
from r3studio.recovery import Recovery,RecoveryHold
from r3studio.presentation import inspection_text
from test_existing import Adapter
from test_generation import pack,Fake

TEXT='모터의 과부하 차단 방식은 제품마다 다릅니다.'
def partial_pack():
 p=pack();p.pop('original_verification')
 for f in p['facts']:f['text']=TEXT
 p['evidence_review']={'diagnostic_only':True,'supported_fact_ids':[],
  'diagnostic':{'reason':'EVIDENCE_ORIGINALS_INCOMPLETE','summary':'원문으로 지원되지 않는 핵심 사실','unverified_claims':[{'text':TEXT,'reason':'원문 지원 미확인'}]}}
 return p
class NoCalls(Fake):
 def ask(self,*a,**k):raise AssertionError('불필요한 독립 검색')
 def object(self,*a,**k):raise AssertionError('불필요한 AI 판정')
class Tests(unittest.TestCase):
 def test_diagnosis_keeps_exact_excerpt_and_never_passes(self):
  p=partial_pack();p['evidence_review']['diagnostic']['unverified_claims'].append({'text':'본문에 없는 10배 주장'})
  r=diagnose_incomplete({'status':'LIVE','content':'<p>'+TEXT+'</p>'},p,{})
  self.assertFalse(r['text_verified']);self.assertEqual(r['review']['fact'],'UNKNOWN')
  self.assertEqual(len(r['review']['findings']),1);self.assertEqual(r['review']['findings'][0]['excerpt'],TEXT)
  self.assertTrue(r['review']['findings'][0]['suggestion'])
 def test_partial_cannot_pass_strict_evaluator(self):
  self.assertFalse(evaluate(NoCalls(),{'status':'SCHEDULED'},partial_pack(),{}) .get('text_verified'))
  with self.assertRaises(EvidenceHold):require_originals(partial_pack())
 def test_original_hold_attaches_partial_without_verification(self):
  p=pack();p.pop('original_verification');quote='실제 원문에 있는 충분히 긴 문장입니다.'
  class Reader:
   def read(self,u):return {'status':'FETCHED','text':quote,'final_url':u}
  class AI:
   def object(self,prompt):return {'sources':[{'source_id':'s1','grade':'A','publisher':'a'},{'source_id':'s2','grade':'A','publisher':'b'}],'claims':[{'fact_id':'0','source_id':'s2','quote':'원문에 없는 번역문 인용입니다.','supported':True}]}
  with self.assertRaises(EvidenceHold) as c:verify_origins(AI(),p,Reader())
  self.assertNotIn('original_verification',c.exception.partial_pack)
  self.assertIn('실제 추출 원문',c.exception.partial_pack['evidence_review']['diagnostic']['unverified_claims'][0]['reason'])
 def test_partial_requires_explicit_opt_in_and_is_not_cached(self):
  s=Store(':memory:');e=EvidenceHold('근거 부족');e.partial_pack=partial_pack()
  with patch('r3studio.evidence.Research.collect',return_value=pack()),patch('r3studio.sources.verify_origins',side_effect=e):
   with self.assertRaises(EvidenceHold):collect_cached(s,Fake(),'t','t','scope')
   self.assertTrue(collect_cached(s,Fake(),'t','t','scope',allow_partial=True)['evidence_review']['diagnostic_only'])
  self.assertEqual(s.db.execute('SELECT count(*) FROM evidence_packs').fetchone()[0],0);s.close()
 def test_existing_partial_completes_diagnosis_images_links_and_records_hold(self):
  s=Store(':memory:');a=Adapter();a.post['content']='<p>'+TEXT+'</p>';Sync(s,a,'blog').run()
  with patch('r3studio.images.inspect_existing_images',return_value={'items':[]}) as images,patch('r3studio.links.inspect_link_access',return_value={'results':[],'factual_support_verified':False}) as links:
   r=inspect_existing(s,a,NoCalls(),'1',partial_pack(),'.')
  images.assert_called_once();links.assert_called_once();self.assertFalse(r['verified']);self.assertEqual(r['grade'],'SCHEDULED_HOLD')
  text=inspection_text({'post_id':'1','status':'SCHEDULED','grade':r['grade'],'details':r})
  self.assertIn('진단 기록 완료',text);self.assertIn('수정 제안:',text)
  self.assertNotIn('연결과 작업 기록 확인',text);s.close()
 def test_image_timeout_preserves_body_diagnosis_and_link_results(self):
  from r3studio.ai import AIError
  s=Store(':memory:');a=Adapter();a.post['content']='<p>'+TEXT+'</p>';Sync(s,a,'blog').run()
  with patch('r3studio.images.inspect_existing_images',side_effect=AIError('응답 시간 초과',{'reason':'TIMEOUT'})),patch('r3studio.links.inspect_link_access',return_value={'results':[]}):
   r=inspect_existing(s,a,NoCalls(),'1',partial_pack(),'.')
  self.assertTrue(r['deep']['review']['findings']);self.assertIn('link_access',r)
  self.assertEqual(r['image_error_diagnostic']['reason'],'TIMEOUT');self.assertFalse(r['verified']);s.close()
 def test_repair_retains_preview_and_requires_strict_modified_evidence(self):
  s=Store(':memory:');a=Adapter();a.post['content']='<p>'+TEXT+'</p>';Sync(s,a,'blog').run()
  class Writer(Fake):
   def object(self,prompt):
    self.prompt=prompt
    return {'content_html':'<p>제품 설명서를 확인하세요.</p><a href="/guide">관련 안내</a>','changes':['미확인 작동 설명 보완']}
  ai=Writer();recovery=Recovery(s,ai,a)
  with patch('r3studio.recovery.collect_cached',side_effect=[partial_pack(),EvidenceHold('수정 본문 근거 부족')]) as collect,patch('r3studio.recovery.inspect_existing_images',return_value={'items':[]}),patch('r3studio.recovery.fast_check',return_value=type('R',(),{})()):
   # Fast checks use dataclasses, so replace asdict only within this proposal test.
   with patch('r3studio.recovery.asdict',return_value={'issues':[]}):r=recovery.propose('1','.')
  self.assertEqual(r['status'],'HOLD');self.assertIn('제품 설명서',r['proposed_content']);self.assertEqual(collect.call_count,2)
  self.assertTrue(collect.call_args_list[0].kwargs['allow_partial']);self.assertNotIn('allow_partial',collect.call_args_list[1].kwargs)
  self.assertEqual(collect.call_args_list[1].kwargs['article'],r['proposed_content'])
  self.assertIn('"facts": []',ai.prompt)
  with self.assertRaises(RecoveryHold):recovery.apply_proposal(r['proposal_id'])
  s.close()
if __name__=='__main__':unittest.main()
