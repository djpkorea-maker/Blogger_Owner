import copy,json,unittest
from r3studio.evidence import Research,EvidenceHold,ledger_diagnostic
from r3studio.presentation import diagnostic_lines
from r3studio.progress import terminal_summary
from test_generation import pack

class AI:
 def __init__(self,ledgers):self.ledgers=ledgers;self.searches=[];self.prompts=[]
 def ask(self,prompt,**kwargs):
  self.searches.append(prompt);return {'citations':[{'url':s['url']} for s in pack()['sources']]}
 def object(self,prompt):
  self.prompts.append(prompt);return copy.deepcopy(self.ledgers[min(len(self.prompts)-1,len(self.ledgers)-1)])

def no_core():
 p=pack()
 for f in p['facts']:f['core']=False
 return p

class Tests(unittest.TestCase):
 def test_core_classification_recovery_reuses_search_and_previous_ledger(self):
  ai=AI([no_core(),pack()]);result=Research(ai).collect('안전하게 이동하는 방법','점검')
  self.assertEqual(len(ai.searches),1);self.assertEqual(len(ai.prompts),2)
  self.assertIn('previous_ledger',ai.prompts[1]);self.assertIn('핵심 사실 추출',ai.prompts[1])
  self.assertEqual(sum(f['core'] is True for f in result['facts']),2)
  self.assertNotIn('original_verification',result)
 def test_insufficient_core_stays_hold_and_then_searches(self):
  ai=AI([no_core()])
  with self.assertRaises(EvidenceHold) as caught:Research(ai).collect('제목','주제')
  self.assertEqual(len(ai.searches),3);self.assertEqual(len(ai.prompts),5)
  self.assertEqual(caught.exception.diagnostic['ledger']['core_facts'],0)
  self.assertIn('핵심 분류 0개','\n'.join(diagnostic_lines(caught.exception.diagnostic)))
 def test_format_then_core_then_repaired_uses_one_search(self):
  bad=pack();bad['facts'][0]['core']='true';bad['facts'][1]['kind']='사용법'
  ai=AI([bad,no_core(),pack()]);result=Research(ai).collect('제목','주제')
  self.assertEqual(len(ai.searches),1);self.assertEqual(len(result['facts']),4)
  self.assertIn('core 형식 오류',ai.prompts[1]);self.assertIn('kind 분류 오류',ai.prompts[1])
 def test_duplicate_fact_ids_repair_reuses_search(self):
  bad=pack();bad['facts'][1]['id']=bad['facts'][0]['id']
  ai=AI([bad,pack()]);Research(ai).collect('t','t');self.assertEqual(len(ai.searches),1)
 def test_insufficient_independent_sources_still_hold(self):
  bad=pack();bad['sources'][1]['url']='https://manufacturer.example/second'
  ai=AI([bad])
  with self.assertRaises(EvidenceHold):Research(ai).collect('t','t')
  self.assertEqual(len(ai.searches),3)
 def test_repair_cannot_invent_source_urls(self):
  bad=pack();bad['sources'][0]['url']='https://invented.example/not-searched'
  ai=AI([no_core(),bad,bad])
  with self.assertRaises(EvidenceHold) as caught:Research(ai).collect('t','t')
  self.assertIn('invented.example',str(caught.exception.diagnostic['unmatched_urls']))
 def test_malformed_fields_diagnostic_does_not_crash(self):
  for p in [None,[],{'facts':None},{'sources':[None],'facts':[None,{'text':[], 'source_ids':[{}]}]}]:
   self.assertEqual(ledger_diagnostic(p)['state'],'FORMAT')
 def test_new_topic_search_is_distinct_from_existing_article(self):
  ai=AI([pack()]);Research(ai).collect('안전하게 이동하는 방법','topic')
  self.assertIn('입력한 새 제목',ai.searches[0]);self.assertIn('전원 차단',ai.searches[0])
 def test_hold_and_error_are_terminal_not_waiting(self):
  for event,label in [(('repair_ready',{'status':'HOLD','reason':'자료 부족'}),'보류 종료'),(('error','시간 초과'),'오류 종료'),(('ai_done',[{'status':'HOLD'}]),'보류 종료'),(('ai_done',{'status':'PASS'}),'작업 종료')]:
   self.assertTrue(terminal_summary(event).startswith(label));self.assertNotIn('대기 중',terminal_summary(event))
 def test_preview_missing_remains_hold(self):
  self.assertTrue(terminal_summary(('repair_ready',{'mode':'REPLACEMENT','replacement_preview_ready':False})).startswith('보류 종료'))
if __name__=='__main__':unittest.main()
