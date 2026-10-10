import copy,unittest
from r3studio.evidence import Research,EvidenceHold
from r3studio.ai import AIError
from r3studio.presentation import diagnostic_lines
from r3studio.tasks import Cancelled
from test_generation import pack
from test_dev73_evidence_progress import AI,no_core

def early_missing():
 a=no_core();a['facts'][2]['kind']='other'
 b=no_core();b['facts']=b['facts'][:2]+b['facts'][3:]
 return [a,b]

class Tests(unittest.TestCase):
 def test_reported_third_search_classification_really_executes_repair(self):
  ai=AI(early_missing()+[no_core(),pack()]);progress=[]
  p=Research(ai).collect('로봇청소기가 문턱에서 걸렸을 때 안전하게 이동하는 방법','안전 이동',lambda *v:progress.append(v))
  self.assertEqual((len(ai.searches),len(ai.prompts)),(3,4))
  self.assertEqual(p['research_budget']['ledger_repairs'],1)
  self.assertEqual(p['research_attempts'][-1]['recovery_state'],'EXECUTED')
  self.assertTrue(any('장부 보완 1/2' in v[0] for v in progress))
  self.assertIn('previous_ledger',ai.prompts[3]);self.assertNotIn('original_verification',p)
 def test_last_search_format_failure_has_two_real_repairs(self):
  ai=AI(early_missing()+[[],[],pack()]);p=Research(ai).collect('t','t')
  self.assertEqual((len(ai.searches),len(ai.prompts)),(3,5));self.assertEqual(p['research_budget']['ledger_repairs'],2)
  self.assertFalse(any(t.get('recovery_state')=='PLANNED' for t in p['research_attempts']))
 def test_budget_exhaustion_does_not_promise_another_repair(self):
  ai=AI(early_missing()+[no_core()])
  with self.assertRaises(EvidenceHold) as c:Research(ai).collect('t','t')
  d=c.exception.diagnostic
  self.assertEqual((len(ai.searches),len(ai.prompts)),(3,5))
  self.assertTrue(d['recovery_exhausted']);self.assertNotIn('recovery',d['attempts'][-1])
  self.assertFalse(any(t.get('recovery_state')=='PLANNED' for t in d['attempts']))
  text='\n'.join(diagnostic_lines(d));self.assertIn('검색 3/3',text);self.assertIn('장부 보완 2/2',text);self.assertIn('실행 완료',text);self.assertIn('현재 실행 중인 복구 없음',text)
 def test_bad_json_does_not_force_more_searches(self):
  ai=AI([[]])
  with self.assertRaises(EvidenceHold) as c:Research(ai).collect('t','t')
  self.assertEqual((len(ai.searches),len(ai.prompts)),(1,3));self.assertTrue(c.exception.diagnostic['recovery_exhausted'])
 def test_empty_sources_do_not_spend_ledger_budget(self):
  class Empty(AI):
   def ask(self,prompt,**kw):self.searches.append(prompt);return {'citations':[]}
  ai=Empty([pack()])
  with self.assertRaises(EvidenceHold) as c:Research(ai).collect('t','t')
  self.assertEqual((len(ai.searches),len(ai.prompts)),(3,0));self.assertEqual(c.exception.diagnostic['research_budget']['ledger_repairs'],0)
 def test_cancel_before_last_search_repair_prevents_fourth_ledger(self):
  ai=AI(early_missing()+[no_core(),pack()])
  def progress(stage,*args):
   if stage.startswith('장부 보완'):raise Cancelled('stop')
  with self.assertRaises(Cancelled):Research(ai).collect('t','t',progress)
  self.assertEqual((len(ai.searches),len(ai.prompts)),(3,3))
 def test_transport_timeout_during_repair_is_not_silently_retried(self):
  class Timeout(AI):
   def object(self,prompt):
    if len(self.prompts)==3:raise AIError('timeout',{'reason':'TIMEOUT'})
    return super().object(prompt)
  ai=Timeout(early_missing()+[no_core()])
  with self.assertRaises(AIError) as c:Research(ai).collect('t','t')
  self.assertEqual(c.exception.diagnostic['reason'],'TIMEOUT');self.assertEqual(len(ai.searches),3)
 def test_json_parse_error_can_repair_after_third_search(self):
  class Parse(AI):
   def object(self,prompt):
    if len(self.prompts)==3:self.prompts.append(prompt);raise ValueError('bad JSON')
    return super().object(prompt)
  ai=Parse(early_missing()+[no_core(),{},pack()]);p=Research(ai).collect('t','t')
  self.assertEqual((len(ai.searches),len(ai.prompts)),(3,5));self.assertEqual(p['research_attempts'][-2]['recovery_state'],'FAILED')
 def test_invented_url_after_final_repair_is_still_blocked(self):
  bad=pack();bad['sources'][0]['url']='https://invented.example/fake'
  ai=AI(early_missing()+[no_core(),bad,bad])
  with self.assertRaises(EvidenceHold) as c:Research(ai).collect('t','t')
  self.assertIn('invented.example',str(c.exception.diagnostic['unmatched_urls']))
  self.assertEqual((len(ai.searches),len(ai.prompts)),(3,5))
 def test_missing_article_excerpt_stays_blocked_with_reused_sources(self):
  ai=AI([pack()])
  with self.assertRaises(EvidenceHold):Research(ai).collect('t','t',article='<p>이 글의 실제 본문은 별도의 안전 점검 방법입니다.</p>')
  self.assertEqual((len(ai.searches),len(ai.prompts)),(1,3))
if __name__=='__main__':unittest.main()
