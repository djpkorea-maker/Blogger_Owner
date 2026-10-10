import json,queue,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import test_dev70_replacement as fixture
from r3studio.replacement import Replacement,replacement_view
from r3studio.generation import Generation
from r3studio.tasks import Cancelled,Cancellation
from r3studio.app import App
from r3studio.ai import AIError
from r3studio.evidence import EvidenceHold
from r3studio.cache_policy import force_whole_review

class Tests(unittest.TestCase):
 def setup_case(self,d):return fixture.Tests().setup_case(d)
 def test_no_body_view_preserves_requested_topic_without_old_title_fallback(self):
  p={'replacement_topic':'로봇청소기가 문턱에서 멈출 때 안전하게 점검하는 방법','before':{'title':'기존 모터 원리'}}
  view=replacement_view(p);self.assertFalse(view['has_body']);self.assertEqual(view['title'],'아직 생성되지 않음');self.assertEqual(view['topic'],p['replacement_topic'])
 def test_same_failed_topic_reuses_job_and_proposal(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);svc=Replacement(s,a,fixture.AI(),d)
   with patch.object(Generation,'resume',return_value={'status':'HOLD'}):
    first=svc.start(pid,'문턱 안전 점검 방법',fixture.Generator());second=svc.start(pid,'문턱 안전 점검 방법',fixture.Generator());third=svc.start_post('1','문턱 안전 점검 방법',fixture.Generator())
   self.assertEqual(first['proposal_id'],second['proposal_id']);self.assertEqual(first['proposal_id'],third['proposal_id']);self.assertEqual(first['replacement_job_id'],third['replacement_job_id']);self.assertEqual(s.db.execute('SELECT count(*) FROM generation_jobs').fetchone()[0],1);s.close()
 def test_failure_before_writer_shows_stage_and_generated_title(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d)
   def failed(g,job):
    p=g.load_job(job)['payload'];p.update(title=p['topic'],reason='원문 접근 실패');g.save(job,'Evidence 원문 확인','HOLD',p)
   with patch.object(Generation,'resume',autospec=True,side_effect=failed):r=Replacement(s,a,fixture.AI(),d).start(pid,'안전하게 문턱을 점검하는 방법',fixture.Generator())
   self.assertEqual(r['proposed_title'],r['replacement_topic']);self.assertEqual(r['replacement_stage'],'Evidence 원문 확인');self.assertEqual(r['reason'],'원문 접근 실패');self.assertFalse(replacement_view(r)['has_body']);s.close()
 def test_body_survives_exception_after_writer(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);gen=fixture.Generator()
   def failed(g,job):
    p=g.load_job(job)['payload'];p.update(title=p['topic'],content=fixture.CONTENT,reason='독립 검사 시간 초과');g.save(job,'독립 Fact 조사','HOLD',p);raise AIError('독립 검사 시간 초과')
   with patch.object(Generation,'resume',autospec=True,side_effect=failed):r=Replacement(s,a,fixture.AI(),d).start(pid,'문턱 안전 점검 안내 방법',gen)
   self.assertEqual(r['proposed_content'],fixture.CONTENT);self.assertEqual(r['replacement_stage'],'독립 Fact 조사');self.assertEqual(gen.calls,[]);self.assertNotIn('plan',r);s.close()
 def test_partial_body_survives_cancellation(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d)
   def stop(g,job):
    p=g.load_job(job)['payload'];p.update(title=p['topic'],content=fixture.CONTENT);g.save(job,'본문 의미 중복','HOLD',p);raise Cancelled('사용자 중단')
   with patch.object(Generation,'resume',autospec=True,side_effect=stop),self.assertRaises(Cancelled):Replacement(s,a,fixture.AI(),d).start(pid,'안전한 문턱 점검 안내',fixture.Generator())
   row=s.db.execute('SELECT payload FROM repair_proposals ORDER BY id DESC LIMIT 1').fetchone();p=json.loads(row[0]);self.assertEqual(p['proposed_content'],fixture.CONTENT);self.assertIn('중단',p['reason']);s.close()
 def test_draft_body_with_invalid_description_is_available_for_preview(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d)
   def failed(g,job):
    p=g.load_job(job)['payload'];p.update(title=p['topic'],draft_content=fixture.CONTENT,reason='Writer 응답 형식 오류');g.save(job,'Writer','HOLD',p)
   with patch.object(Generation,'resume',autospec=True,side_effect=failed):r=Replacement(s,a,fixture.AI(),d).start(pid,'안전한 청소기 점검 순서',fixture.Generator())
   self.assertTrue(replacement_view(r)['has_body']);self.assertEqual(r['status'],'HOLD');self.assertNotIn('plan',r);s.close()
 def test_unrelated_new_generation_topic_is_not_rebound_to_replacement(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);Generation(s,fixture.AI(),'blog').reserve('안전한 청소기 점검 순서')
   r=Replacement(s,a,fixture.AI(),d).start(pid,'안전한 청소기 점검 순서',fixture.Generator());self.assertNotIn('replacement_job_id',r);self.assertIn('이미 사용한 주제',r['reason']);s.close()
 def test_ready_preview_repeat_does_not_generate_or_upload_again(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);svc,r=fixture.Tests().start(s,a,pid,d)
   with patch.object(Generation,'resume',side_effect=AssertionError('unexpected AI')):again=svc.start_post('1',r['replacement_topic'],fixture.Generator())
   self.assertEqual(again['proposal_id'],r['proposal_id']);self.assertEqual(again['image_choices'],r['image_choices']);s.close()
 def test_default_worker_reuses_previous_records_after_restart(self):
  with tempfile.TemporaryDirectory() as d:
   for attempt in range(2):
    app=App.__new__(App);app.base=Path(d);app.events=queue.Queue();app.cancel_token=Cancellation();app.worker(True)
    events=[]
    while not app.events.empty():events.append(app.events.get())
    result=events[-1];self.assertEqual(result[0],'done')
    if attempt:self.assertEqual(result[1]['reused'],3);self.assertEqual(result[2]['reused'],3);self.assertEqual(result[2]['checked'],0)
 def test_dev71_force_policy_preserves_manual_refresh(self):
  self.assertFalse(force_whole_review());self.assertTrue(force_whole_review(force=True))
 def test_generation_uses_requested_replacement_title_without_ai_refill(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);svc=Replacement(s,a,fixture.AI(),d)
   with patch.object(Generation,'resume',return_value={'status':'HOLD'}):r=svc.start(pid,'로봇청소기가 문턱에서 멈출 때 안전하게 점검하는 방법',fixture.Generator())
   class AI(fixture.AI):
    def object(self,prompt):
     if 'duplicate:boolean' in prompt:return {'duplicate':False,'reason':'다른 질문'}
     if '블로그 글을 작성하세요' in prompt:return {'content_html':fixture.CONTENT,'search_description':'안전 점검 순서'}
     return super().object(prompt)
   from test_generation import pack
   with patch('r3studio.generation.Research.collect',return_value=pack()),patch('r3studio.semantic.title_profile',return_value={'duplicate':False}),patch('r3studio.semantic.body_review',return_value={'duplicate':False}),patch('r3studio.titles.refill',side_effect=AssertionError('입력 제목 변경 금지')):
    g=Generation(s,AI(),'blog');g.resume(r['replacement_job_id'])
   payload=g.load_job(r['replacement_job_id'])['payload'];self.assertEqual(payload['title'],r['replacement_topic']);self.assertEqual(payload['content'],fixture.CONTENT);s.close()
 def test_requested_title_conflict_is_reported_without_silent_replacement(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d)
   with patch.object(Generation,'resume',return_value={'status':'HOLD'}):r=Replacement(s,a,fixture.AI(),d).start(pid,'청소기 바퀴 관리',fixture.Generator())
   class AI(fixture.AI):
    def object(self,p):return {'duplicate':False,'reason':''}
   g=Generation(s,AI(),'blog');result=g.resume(r['replacement_job_id']);self.assertIn('입력한 새 제목 검토 필요',result['reason']);self.assertNotIn('content',g.load_job(r['replacement_job_id'])['payload']);s.close()

if __name__=='__main__':unittest.main()
