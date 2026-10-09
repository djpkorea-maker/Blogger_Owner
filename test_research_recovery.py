import unittest
from r3studio.evidence import Research,validate_pack,EvidenceHold
from test_generation import pack
class AI:
 def __init__(self):self.searches=0;self.formats=0
 def ask(self,*args,**kwargs):self.searches+=1;return {'citations':[{'url':s['url']} for s in pack()['sources']]}
 def object(self,prompt):self.formats+=1;return []
class Tests(unittest.TestCase):
 def test_bad_format_recovery_is_bounded_and_reuses_search(self):
  ai=AI()
  with self.assertRaises(EvidenceHold) as caught:Research(ai).collect('제목','주제')
  self.assertEqual(ai.searches,1);self.assertEqual(ai.formats,3);self.assertEqual(len(caught.exception.attempts),3)
 def test_malformed_source_url_has_controlled_hold(self):
  p=pack();p['sources'][0]['url']='https://['
  with self.assertRaises(EvidenceHold):validate_pack(p)
if __name__=='__main__':unittest.main()
