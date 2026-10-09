import unittest
from r3studio.titles import refill
from r3studio.evidence import EvidenceHold
class AI:
 def __init__(self,items):self.items=iter(items);self.calls=0
 def object(self,p):self.calls+=1;return {'title':next(self.items)}
class Tests(unittest.TestCase):
 def test_bad_and_duplicate_candidates_are_refilled(self):
  ai=AI(['','기존 사용 조건 확인 방법','새로운 용기 표시 확인 순서']);records=[]
  self.assertEqual(refill(ai,'용기',['기존 사용 조건 확인 방법'],lambda *x:records.append(x)),'새로운 용기 표시 확인 순서');self.assertEqual(len(records),3)
 def test_retry_is_bounded(self):
  ai=AI(['','',''])
  with self.assertRaises(EvidenceHold):refill(ai,'주제',[])
  self.assertEqual(ai.calls,3)
if __name__=='__main__':unittest.main()
