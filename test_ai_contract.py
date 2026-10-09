import unittest
from r3studio.ai import output_blocks,AIError,Gemini
class Tests(unittest.TestCase):
 def test_incomplete_text_is_not_accepted(self):
  ai=Gemini('key','model',lambda p:{'status':'incomplete','steps':[{'type':'model_output','content':[{'type':'text','text':'부분 본문'}]}]})
  with self.assertRaises(AIError):ai.ask('본문')
 def test_malformed_response_is_controlled(self):
  for raw in ([],{'steps':None},{'steps':[None]},{'outputs':[None]}):
   with self.assertRaises(AIError):output_blocks(raw)
 def test_completed_response_parses(self):
  self.assertEqual(output_blocks({'status':'completed','steps':[{'type':'model_output','content':[{'type':'text','text':'완료'}]}]})[0]['text'],'완료')
if __name__=='__main__':unittest.main()
