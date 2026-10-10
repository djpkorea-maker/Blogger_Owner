import unittest
from unittest.mock import patch
from r3studio.ai import Gemini,AIError
from r3studio.evidence import Research
from r3studio.tasks import Cancelled
from test_generation import pack

def reply():return {'status':'completed','outputs':[{'type':'text','text':'answer','annotations':[]}]}
class Tests(unittest.TestCase):
 def test_low_thinking_is_only_documented_model_search(self):
  calls=[];ai=Gemini('secret','gemini-3.8-flash',lambda p:calls.append(p) or reply())
  ai.ask('search',search=True);ai.ask('quality',json_output=True)
  self.assertEqual(calls[0]['generation_config'],{'thinking_level':'low'});self.assertNotIn('generation_config',calls[1])
  ai=Gemini('secret','custom-model',lambda p:calls.append(p) or reply());ai.ask('search',search=True);self.assertNotIn('generation_config',calls[-1])
 def test_timeout_budget_restores_after_request_failure_and_records_safe_metadata(self):
  budgets=[]
  def transport(p):budgets.append(ai.request_timeout_seconds);raise AIError('timeout',{'reason':'TIMEOUT'})
  ai=Gemini('secret','gemini-3.8-flash',transport)
  with self.assertRaises(AIError) as caught:ai.ask('article',search=True,timeout_seconds=60)
  self.assertEqual(budgets,[60]);self.assertEqual(ai.request_timeout_seconds,120)
  self.assertEqual(caught.exception.diagnostic['timeout_seconds'],60);self.assertNotIn('secret',str(caught.exception.diagnostic));self.assertEqual(caught.exception.diagnostic['thinking_level'],'low')
 def test_timeout_recovery_once_and_shorter_request_then_normal_validation(self):
  class AI:
   calls=[]
   def ask(self,prompt,**kw):
    self.calls.append((prompt,kw))
    if len(self.calls)==1:raise AIError('timeout',{'reason':'TIMEOUT','elapsed_seconds':120})
    return {'citations':[{'url':s['url']} for s in pack()['sources']]}
   def object(self,prompt):return pack()
  ai=AI();result=Research(ai).collect('title','topic')
  self.assertEqual(len(ai.calls),2);self.assertEqual(ai.calls[1][1]['timeout_seconds'],60);self.assertEqual(len(result['facts']),4);self.assertEqual(len(result['research_attempts']),1)
 def test_second_timeout_stops_and_keeps_first_failure_record(self):
  class AI:
   count=0
   def ask(self,*a,**k):self.count+=1;raise AIError('timeout',{'reason':'TIMEOUT','elapsed_seconds':k.get('timeout_seconds',120)})
  ai=AI()
  with self.assertRaises(AIError) as caught:Research(ai).collect('title','topic')
  self.assertEqual(ai.count,2);self.assertTrue(caught.exception.diagnostic['recovery_used']);self.assertEqual(len(caught.exception.diagnostic['search_attempts']),1)
 def test_quota_or_auth_errors_do_not_trigger_retry(self):
  for reason in ('RESOURCE_EXHAUSTED','INVALID_API_KEY','NETWORK'):
   class AI:
    count=0
    def ask(self,*a,**k):self.count+=1;raise AIError('error',{'reason':reason})
   ai=AI()
   with self.assertRaises(AIError):Research(ai).collect('title','topic')
   self.assertEqual(ai.count,1)
 def test_cancel_before_recovery_prevents_second_request(self):
  class AI:
   count=0
   def ask(self,*a,**k):self.count+=1;raise AIError('timeout',{'reason':'TIMEOUT'})
  def progress(stage,*args):
   if '축소 복구' in stage:raise Cancelled('stop')
  ai=AI()
  with self.assertRaises(Cancelled):Research(ai).collect('title','topic',progress)
  self.assertEqual(ai.count,1)
if __name__=='__main__':unittest.main()
