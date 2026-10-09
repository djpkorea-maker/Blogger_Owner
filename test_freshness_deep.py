import unittest
from datetime import datetime,timedelta,timezone
from r3studio.freshness import is_fresh
from r3studio.deep import evaluate
from test_generation import Fake,pack
class Tests(unittest.TestCase):
 def test_missing_naive_future_and_expired_time_rejected(self):
  for value in (None,'broken','2026-10-09T09:00:00',(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()):self.assertFalse(is_fresh(value,3600))
  self.assertTrue(is_fresh(datetime.now(timezone.utc).isoformat(),3600))
 def test_review_issue_cannot_pass_even_with_high_score(self):
  class AI(Fake):
   def object(self,p):r=super().object(p);r['issues']=['핵심 조건 추가 필요'];return r
  r=evaluate(AI(),{'status':'DRAFT'},pack(),{'issues':[]});self.assertFalse(r['text_verified'])
 def test_non_object_review_is_held(self):
  class AI(Fake):
   def object(self,p):return []
  self.assertEqual(evaluate(AI(),{'status':'SCHEDULED'},pack(),{'issues':[]})['grade'],'SCHEDULED_HOLD')
if __name__=='__main__':unittest.main()
