import json,tempfile,unittest
from unittest.mock import patch
import test_dev70_replacement as f
from test_generation import pack
from r3studio.replacement import Replacement
from r3studio.generation import Generation
from r3studio.job_peers import comparison_jobs
from r3studio.semantic import duplicate_explanation,title_profile,body_review
from r3studio.evidence import EvidenceHold
from r3studio.images import ImageHold
from r3studio.images import inspect_bytes
from r3studio.sync import digest
from r3studio.gates import Document

TITLE1='로봇청소기가 문턱에서 멈출 때 안전하게 점검하는 방법'
TITLE2='로봇청소기가 문턱에서 걸렸을 때 안전하게 이동하는 방법'
SECOND_BODY=f.CONTENT.replace('<h2>청소기 점검</h2>','<h2>'+TITLE2+'</h2>')
PROFILE={'core_question':'문턱에서 멈춘 청소기 점검','search_intent':'안전 점검','h2':['전원 차단','사용 설명서 확인'],'key_facts':['바닥 장애물 확인'],'practical_outcome':'안전한 점검'}

class Tests(unittest.TestCase):
 def setup_case(self,d):return f.Tests().setup_case(d)
 def failed(self,svc,pid,topic):
  def stop(g,job):
   p=g.load_job(job)['payload'];p.update(title=topic,semantic_title={'profile':dict(PROFILE)},reason='조사 보류');g.store.db.execute('UPDATE generation_jobs SET title=? WHERE id=?',(topic,job));g.save(job,'Evidence','HOLD',p)
  with patch.object(Generation,'resume',autospec=True,side_effect=stop):return svc.start(pid,topic,f.Generator())
 def new_request(self,svc,pid,topic=TITLE2):
  with patch.object(Generation,'resume',return_value={'status':'HOLD'}):return svc.start(pid,topic,f.Generator())
 def target(self,s,r):return Generation(s,f.AI(),'blog').load_job(r['replacement_job_id'])['payload']['replacement_target']
 def test_reported_failed_first_title_does_not_block_second_title_or_body_or_images(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d)
   class AI(f.AI):
    blocked=None
    seen=[]
    def object(self,prompt):
     if 'R3 SEMANTIC TITLE' in prompt or 'R3 SEMANTIC BODY' in prompt:
      data=json.loads(prompt.split('\n',1)[1]);self.seen.append(data['peers']);ids=[p['id'] for p in data['peers'] if p['id']==self.blocked]
      return {'duplicate':bool(ids),'reason':'실패한 첫 작업과 중복' if ids else '다른 실제 글과 독립','duplicate_ids':ids,'profile':dict(PROFILE)}
     if 'duplicate:boolean' in prompt:return {'duplicate':False,'reason':'독립적인 질문'}
     if '블로그 글을 작성하세요' in prompt:return {'content_html':SECOND_BODY,'search_description':'문턱에서 멈춘 청소기를 안전하게 점검합니다.'}
     return super().object(prompt)
   ai=AI();svc=Replacement(s,a,ai,d)
   with patch('r3studio.generation.Research.collect',side_effect=[EvidenceHold('재현용 원문 조사 보류'),pack()]):
    first=svc.start(pid,TITLE1,f.Generator());ai.blocked='job:'+str(first['replacement_job_id']);second=svc.start(pid,TITLE2,f.Generator())
   self.assertNotIn('proposed_content',first);self.assertEqual(second['proposed_title'],TITLE2);self.assertTrue(second['replacement_preview_ready'],second['reason']);self.assertEqual(len(Document(second['proposed_content']).images),2);self.assertNotIn('plan',second)
   self.assertGreaterEqual(len(ai.seen),3)
   for peers in ai.seen:
    self.assertNotIn(ai.blocked,[p['id'] for p in peers]);self.assertIn('post:2',[p['id'] for p in peers])
   old=Generation(s,ai,'blog').load_job(first['replacement_job_id']);self.assertEqual(old['status'],'HOLD');self.assertEqual(old['title'],TITLE1);s.close()
 def test_final_replacement_validation_keeps_other_real_posts(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);svc,r=f.Tests().start(s,a,pid,d)
   self.failed(svc,pid,'이전 실패한 다른 교체 제목')
   a.upload_image=lambda data,mime,name,rid:{'ok':True,'publicImageUrl':'https://lh3.googleusercontent.com/'+rid,'byte_hash':inspect_bytes(data)['byte_hash']}
   def check(store,ai,title,content,*args):return [{'result':'PASS','url':im['src'],'alt':im['alt'],'article_hash':digest({'title':title,'content':content})} for im in Document(content).images]
   with patch('r3studio.repair_images.collect_cached',return_value=pack()),patch('r3studio.repair_images.evaluate',return_value={'text_verified':True}),patch('r3studio.repair_images.check_public_images',side_effect=check),patch('r3studio.finalize.decide',return_value={'grade':'PASS'}) as final,patch('r3studio.repair_images.check_links',return_value={'pass':True}):out=svc.images.validate(r['proposal_id'])
   self.assertEqual(out['status'],'PASS',out.get('reason'));self.assertEqual([p['post_id'] for p in final.call_args.args[2]],['2']);self.assertEqual(out['plan']['post_id'],'1');self.assertNotIn('r3-local:',out['plan']['proposal']['content']);s.close()
 def test_nearly_identical_title_is_allowed_for_same_unapplied_target(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);svc=Replacement(s,a,f.AI(),d);first=self.failed(svc,pid,TITLE1);second=self.new_request(svc,pid,TITLE1+' 상세 안내')
   self.assertIn('replacement_job_id',second);self.assertNotEqual(first['replacement_job_id'],second['replacement_job_id']);s.close()
 def test_new_publication_keeps_failed_topic_exclusion(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);svc=Replacement(s,a,f.AI(),d);self.failed(svc,pid,TITLE1)
   with self.assertRaisesRegex(EvidenceHold,'이미 사용한 주제'):Generation(s,f.AI(),'blog').reserve(TITLE1)
   s.close()
 def test_different_target_keeps_the_previous_job_as_peer(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);svc=Replacement(s,a,f.AI(),d);first=self.failed(svc,pid,TITLE1)
   with patch.object(Generation,'resume',return_value={'status':'HOLD'}):second=svc.start_post('2','다른 청소기의 안전한 관리와 점검',f.Generator())
   jobs=comparison_jobs(s,'blog',second['replacement_job_id'],self.target(s,second));self.assertIn(first['replacement_job_id'],[r['id'] for r in jobs]);s.close()
 def test_applied_and_uncertain_jobs_are_not_exempted(self):
  for state in ('APPLIED','APPLYING','NEEDS_RECONCILE'):
   with self.subTest(state=state),tempfile.TemporaryDirectory() as d:
    s,a,pid=self.setup_case(d);svc=Replacement(s,a,f.AI(),d);first=self.failed(svc,pid,TITLE1);second=self.new_request(svc,pid)
    s.db.execute('UPDATE repair_proposals SET status=? WHERE id=?',(state,first['proposal_id']));s.db.commit()
    jobs=comparison_jobs(s,'blog',second['replacement_job_id'],self.target(s,second));self.assertIn(first['replacement_job_id'],[r['id'] for r in jobs]);s.close()
 def test_passed_but_unapplied_alternative_is_exempted(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);svc=Replacement(s,a,f.AI(),d);first=self.failed(svc,pid,TITLE1);second=self.new_request(svc,pid)
   s.db.execute('UPDATE repair_proposals SET status="PASS" WHERE id=?',(first['proposal_id'],));s.db.commit()
   self.assertNotIn(first['replacement_job_id'],[r['id'] for r in comparison_jobs(s,'blog',second['replacement_job_id'],self.target(s,second))]);s.close()
 def test_corrupt_prior_payload_is_kept_for_protection(self):
  for raw in ('[]','{broken'):
   with self.subTest(raw=raw),tempfile.TemporaryDirectory() as d:
    s,a,pid=self.setup_case(d);svc=Replacement(s,a,f.AI(),d);first=self.failed(svc,pid,TITLE1);second=self.new_request(svc,pid)
    s.db.execute('UPDATE generation_jobs SET payload=? WHERE id=?',(raw,first['replacement_job_id']));s.db.commit()
    self.assertIn(first['replacement_job_id'],[r['id'] for r in comparison_jobs(s,'blog',second['replacement_job_id'],self.target(s,second))]);s.close()
 def test_wrong_job_binding_is_not_exempted(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);svc=Replacement(s,a,f.AI(),d);first=self.failed(svc,pid,TITLE1);second=self.new_request(svc,pid)
   row=s.db.execute('SELECT payload FROM repair_proposals WHERE id=?',(first['proposal_id'],)).fetchone();p=json.loads(row[0]);p['replacement_job_id']=999
   s.db.execute('UPDATE repair_proposals SET payload=? WHERE id=?',(json.dumps(p),first['proposal_id']));s.db.commit()
   self.assertIn(first['replacement_job_id'],[r['id'] for r in comparison_jobs(s,'blog',second['replacement_job_id'],self.target(s,second))]);s.close()
 def test_uncertain_current_replacement_cannot_invoke_exception(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);svc=Replacement(s,a,f.AI(),d);second=self.new_request(svc,pid);target=self.target(s,second)
   s.db.execute('UPDATE repair_proposals SET status="APPLYING" WHERE id=?',(second['proposal_id'],));s.db.commit()
   with self.assertRaises(ImageHold):comparison_jobs(s,'blog',target=target)
   s.close()
 def test_mismatched_original_id_and_corrupt_proposal_are_not_exempted(self):
  for corruption in ('id','json'):
   with self.subTest(corruption=corruption),tempfile.TemporaryDirectory() as d:
    s,a,pid=self.setup_case(d);svc=Replacement(s,a,f.AI(),d);first=self.failed(svc,pid,TITLE1);second=self.new_request(svc,pid)
    p=json.loads(s.db.execute('SELECT payload FROM repair_proposals WHERE id=?',(first['proposal_id'],)).fetchone()[0]);p['before']['id']='wrong-post'
    raw='[]' if corruption=='json' else json.dumps(p)
    s.db.execute('UPDATE repair_proposals SET payload=? WHERE id=?',(raw,first['proposal_id']));s.db.commit()
    self.assertIn(first['replacement_job_id'],[r['id'] for r in comparison_jobs(s,'blog',second['replacement_job_id'],self.target(s,second))]);s.close()
 def test_other_blog_jobs_never_enter_comparison(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);other=Generation(s,f.AI(),'another-blog').reserve(TITLE1);self.assertNotIn(other,[r['id'] for r in comparison_jobs(s,'blog')]);s.close()
 def test_same_topic_resume_preserves_work_number(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);svc=Replacement(s,a,f.AI(),d);first=self.failed(svc,pid,TITLE1)
   with patch.object(Generation,'resume',return_value={'status':'HOLD'}):again=svc.start_post('1',TITLE1,f.Generator())
   self.assertEqual(first['proposal_id'],again['proposal_id']);self.assertEqual(first['replacement_job_id'],again['replacement_job_id']);s.close()
 def test_unbound_legacy_jobs_are_not_assumed_to_be_same_target(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);legacy=Generation(s,f.AI(),'blog').reserve('다른 과거 청소기 주제');second=self.new_request(Replacement(s,a,f.AI(),d),pid)
   self.assertIn(legacy,[r['id'] for r in comparison_jobs(s,'blog',second['replacement_job_id'],self.target(s,second))]);s.close()
 def test_actual_other_blogger_title_still_blocks(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);svc=Replacement(s,a,f.AI(),d);r=self.new_request(svc,pid,'청소기 바퀴 관리')
   class AI(f.AI):
    def object(self,p):return {'duplicate':False,'reason':''}
   out=Generation(s,AI(),'blog').resume(r['replacement_job_id']);self.assertIn('기존 제목과 동일',out['reason']);s.close()
 def test_actual_other_blogger_duplicate_still_blocks_before_research(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);r=self.new_request(Replacement(s,a,f.AI(),d),pid)
   class AI(f.AI):
    def object(self,p):return {'duplicate':True,'reason':'다른 Blogger 글과 같은 답'}
   with patch('r3studio.generation.Research.collect',side_effect=AssertionError('조사 호출 금지')):out=Generation(s,AI(),'blog').resume(r['replacement_job_id'])
   self.assertIn('기존 LIVE 중복',out['reason']);s.close()
 def test_explanation_distinguishes_unwritten_profile_and_real_body(self):
  result={'reason':'구성이 비슷함','duplicate_ids':['job:1','post:2']};peers=[{'id':'job:1','comparison_basis':'PLANNED_PROFILE'},{'id':'post:2','comparison_basis':'BLOGGER_BODY'}]
  text=duplicate_explanation(result,peers);self.assertIn('본문 미작성 · 예상 구성 비교',text);self.assertIn('Blogger 실제 본문',text)
 def test_model_cannot_return_exempted_job_id(self):
  class AI:
   def object(self,p):return {'duplicate':True,'reason':'잘못된 대상','duplicate_ids':['job:1'],'profile':dict(PROFILE)}
  with self.assertRaises(EvidenceHold):title_profile(AI(),TITLE2,TITLE2,[{'id':'post:2','title':'다른 글','summary':'내용'}])
  with self.assertRaises(EvidenceHold):body_review(AI(),TITLE2,f.CONTENT,[{'id':'post:2','title':'다른 글','summary':'내용'}])

if __name__=='__main__':unittest.main()
