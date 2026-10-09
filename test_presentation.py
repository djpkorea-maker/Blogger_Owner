import tempfile
import unittest
import queue
from pathlib import Path
from r3studio.sync import Store
from r3studio.tasks import TaskLog,finish_error,Cancelled
from r3studio.presentation import result_text,history_text

class Tests(unittest.TestCase):
 def test_google_summary_separates_access_from_indexing(self):
  from r3studio.presentation import google_text
  text=google_text({'technical_status':'ACCESSIBLE','index_status':'확인 불가','public_crawl':{'robots_state':'ALLOWED','sitemap_state':'FOUND'},'canonical':['https://example.com/post']})
  self.assertIn('공개 접근 가능',text);self.assertIn('Google 색인: 확인 불가',text);self.assertIn('대표 주소: https://example.com/post',text)
 def test_summary_distinguishes_verified_and_pending(self):
  from r3studio.presentation import inspection_summary
  text=inspection_summary({'listed':4,'changed':1,'reused':3},{'checked':1,'reused':3},[{'grade':g} for g in ('PASS','SCHEDULED_HOLD','EMPTY_BOTH','NEEDS_DEEP')])
  self.assertIn('PASS 1',text);self.assertIn('누락 1',text);self.assertIn('검증 미완료 1',text)
 def test_ui_sync_worker_records_complete_and_cancelled(self):
  from r3studio.app import App
  from r3studio.tasks import Cancellation
  with tempfile.TemporaryDirectory() as d:
   app=App.__new__(App);app.base=Path(d);app.events=queue.Queue();app.cancel_token=Cancellation()
   app.worker(True)
   events=[]
   while not app.events.empty():events.append(app.events.get())
   self.assertEqual(events[-1][0],'done')
   self.assertTrue(any(e[0]=='progress' for e in events))
   app.cancel_token.request();app.worker(True)
   self.assertEqual(app.events.get()[0],'error')
   s=Store(d+'/demo.sqlite3')
   self.assertEqual([r[0] for r in s.db.execute('SELECT status FROM task_runs ORDER BY id')],['COMPLETED','CANCELLED']);s.close()
 def test_generation_cancel_persists_hold_and_propagates(self):
  from r3studio.app import DemoAdapter
  from r3studio.sync import Sync
  from r3studio.generation import Generation
  class AI:
   def object(self,prompt):raise Cancelled('중단 요청')
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');Sync(s,DemoAdapter(),'DEMO').run()
   with self.assertRaises(Cancelled):Generation(s,AI(),'DEMO').generate('새로운 안전 점검 주제')
   self.assertEqual(s.db.execute('SELECT status FROM generation_jobs').fetchone()[0],'HOLD');s.close()
 def test_result_omits_raw_payload_and_shows_hold_reason(self):
  text=result_text({'job_id':7,'status':'HOLD','payload':{'reason':'이미지 검사 필요','content':'비공개 본문','api_key':'secret'}})
  self.assertIn('이미지 검사 필요',text);self.assertIn('발행할 수 없습니다',text)
  self.assertNotIn('secret',text);self.assertNotIn('비공개 본문',text)
 def test_interrupted_task_is_not_claimed_complete(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');task=TaskLog(s,'생성')
   self.assertIn('종료 미확인',history_text(list(s.db.execute('SELECT * FROM task_runs'))))
   finish_error(task,Cancelled('secret'))
   row=s.db.execute('SELECT * FROM task_runs').fetchone()
   self.assertEqual(row['status'],'CANCELLED');self.assertNotIn('secret',row['details']);s.close()
 def test_failure_log_does_not_persist_sensitive_error(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');task=TaskLog(s,'조회');finish_error(task,ValueError('secret'))
   row=s.db.execute('SELECT * FROM task_runs').fetchone()
   self.assertEqual(row['status'],'FAILED');self.assertEqual(row['details'],'ValueError');s.close()
if __name__=='__main__':unittest.main()
