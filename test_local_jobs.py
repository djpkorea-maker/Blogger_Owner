import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from r3studio.sync import Store
from r3studio.generation import Generation
from r3studio.local_jobs import read_jobs
from r3studio.app import App
from r3studio.tasks import Cancellation
class Tests(unittest.TestCase):
 def test_empty_database_is_readable_without_job_tables(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');self.assertEqual(read_jobs(s),[]);s.close()
 def test_ui_load_never_initializes_bridge_or_ai(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/studio.sqlite3');g=Generation(s,None,'blog');job=g.reserve('저장된 주제');g.save(job,'작성 대기','HOLD',{'reason':'근거 확인 필요'});s.close()
   app=App.__new__(App);app.base=Path(d);app.events=queue.Queue();app.cancel_token=Cancellation()
   with patch('r3studio.bridge.BridgeAdapter.from_environment',side_effect=AssertionError('외부 조회 금지')),patch('r3studio.ai.Gemini.from_environment',side_effect=AssertionError('AI 초기화 금지')):
    app.ai_worker('load_job',job)
   event=app.events.get();self.assertEqual(event[0],'ai_done');self.assertTrue(event[1]['local_only']);self.assertEqual(event[1]['payload']['reason'],'근거 확인 필요')
if __name__=='__main__':unittest.main()
