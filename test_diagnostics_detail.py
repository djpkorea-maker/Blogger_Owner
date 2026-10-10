import io
import json
import tempfile
import unittest
import urllib.error
from unittest.mock import patch
from r3studio.ai import Gemini,AIError,connection_error
from r3studio.tasks import TaskLog,finish_error
from r3studio.sync import Store
from r3studio.presentation import history_text,inspection_text

class DiagnosticsTests(unittest.TestCase):
 def test_http_failure_records_code_without_server_secrets(self):
  for code in (400,401,402,403,404,429,500,503,504):
   error=urllib.error.HTTPError('https://example.test?key=secret',code,'secret',{'Retry-After':'12'},io.BytesIO(json.dumps({'error':{'status':'RESOURCE_EXHAUSTED','message':'sensitive article secret'}}).encode()))
   with patch('urllib.request.urlopen',side_effect=error):
    with self.assertRaises(AIError) as raised:Gemini('secret','test-model').ask('private article')
   exc=raised.exception
   self.assertEqual(exc.diagnostic['http_status'],code)
   self.assertNotIn('secret',str(exc));self.assertNotIn('private article',str(exc))
   self.assertEqual(exc.diagnostic['retry_after_seconds'],12)
 def test_timeout_and_network_are_distinguished(self):
  for cause,reason in ((TimeoutError(),'TIMEOUT'),(urllib.error.URLError('secret'),'NETWORK')):
   with patch('urllib.request.urlopen',side_effect=cause):
    with self.assertRaises(AIError) as raised:Gemini('secret','test-model').ask('text')
   self.assertEqual(raised.exception.diagnostic['reason'],reason)
   self.assertNotIn('secret',str(raised.exception))
 def test_timeout_setting_and_elapsed_diagnostics_without_retry(self):
  with patch('urllib.request.urlopen',side_effect=TimeoutError()) as request,patch('r3studio.ai.time.monotonic',side_effect=[10,130]):
   with self.assertRaises(AIError) as raised:Gemini('secret','test-model').ask('text',search=True)
  self.assertEqual(request.call_count,1);self.assertEqual(request.call_args.kwargs['timeout'],120)
  self.assertEqual(raised.exception.diagnostic['elapsed_seconds'],120)
  self.assertEqual(raised.exception.diagnostic['request_type'],'검색 근거 조사')
 def test_safe_diagnostics_survive_task_history(self):
  with tempfile.TemporaryDirectory() as d:
   store=Store(d+'/db');task=TaskLog(store,'심층 검사')
   finish_error(task,connection_error(429,'test-model',b'{"error":{"message":"secret"}}'))
   text=history_text(list(store.db.execute('SELECT * FROM task_runs')))
   self.assertIn('429',text);self.assertIn('요청 횟수',text);self.assertNotIn('secret',text);store.close()
 def test_fast_counts_do_not_claim_pixels_or_links_passed(self):
  text=inspection_text({'post_id':'1','status':'SCHEDULED','grade':'SCHEDULED_HOLD','details':{'metrics':{'images':2,'internal_links':0},'issues':['내부링크 확인 필요'],'verified':False}})
  self.assertIn('내부링크 0개',text);self.assertIn('미검사',text);self.assertIn('실제 예약을 중지하지 않습니다',text)
  self.assertNotIn('본문 심층 검사: 완료',text)
 def test_failure_and_unrun_stages_remain_distinct(self):
  text=inspection_text({'post_id':'1','grade':'B','details':{'deep':{'review':{'fact':'PASS'}},'check_states':{'images':'미완료 · 이미지 2: ALT 불일치','links':'미검사'},'verified':False}})
  self.assertIn('이미지 2: ALT 불일치',text);self.assertIn('링크 공개 접근 검사: 미검사',text)
 def test_findings_include_location_reason_and_proposal(self):
  text=inspection_text({'post_id':'1','grade':'B','details':{'deep':{'review':{'findings':[{'location':'두 번째 문단','excerpt':'문제 문장','reason':'근거 부족','suggestion':'조건을 명시하세요.'}]}},'verified':False}})
  for expected in ('두 번째 문단','문제 문장','근거 부족','조건을 명시하세요.'):self.assertIn(expected,text)
if __name__=='__main__':unittest.main()
