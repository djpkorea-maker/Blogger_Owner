import unittest
from r3studio.readiness import require_settings,readiness_text
class Tests(unittest.TestCase):
 def test_all_non_ai_actions_work_without_ai_configuration(self):
  from r3studio.readiness import AI_ACTIONS,KNOWN_ACTIONS,LOCAL_ACTIONS
  for action in KNOWN_ACTIONS-AI_ACTIONS-LOCAL_ACTIONS:
   with self.subTest(action=action):require_settings(self.values(),action)
  for action in LOCAL_ACTIONS:
   with self.subTest(action=action):require_settings({},action)
 def test_all_ai_actions_require_ai_configuration(self):
  from r3studio.readiness import AI_ACTIONS
  for action in AI_ACTIONS:
   with self.subTest(action=action),self.assertRaises(ValueError):require_settings(self.values(),action)
 def test_malformed_url_is_a_controlled_problem(self):
  values=self.values();values['R3_BRIDGE_URL']='https://[';values['R3_GSC_PROPERTY']='https://['
  text=readiness_text(values);self.assertIn('형식',text)
  with self.assertRaises(ValueError):require_settings(values,'sync')
 def test_adapter_rejects_same_invalid_addresses(self):
  from r3studio.bridge import BridgeAdapter
  for url in ('https://script.google.com/not-a-deployment/exec','https://user@script.google.com/macros/s/abc/exec','https://script.google.com/macros/s/abc/exec?secret=private'):
   with self.assertRaises(ValueError):BridgeAdapter(url,'key','123')
 def values(self):return {'R3_BLOG_ID':'123','R3_BRIDGE_URL':'https://script.google.com/macros/s/abc/exec','R3_BRIDGE_SECRET':'private-secret'}
 def test_read_only_confirmation_needs_no_ai(self):require_settings(self.values(),'reconcile')
 def test_generation_requires_ai_before_requests(self):
  with self.assertRaises(ValueError):require_settings(self.values(),'generate')
 def test_secret_never_displayed_and_input_not_verified(self):
  text=readiness_text(self.values());self.assertNotIn('private-secret',text);self.assertIn('실제 연결 미확인',text)
 def test_editor_url_rejected(self):
  values=self.values();values['R3_BRIDGE_URL']='https://script.google.com/macros/s/abc/dev'
  with self.assertRaises(ValueError):require_settings(values,'sync')
if __name__=='__main__':unittest.main()
