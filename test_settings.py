import tempfile
import unittest
from pathlib import Path
from r3studio.settings import Settings,SettingsError
class Tests(unittest.TestCase):
 def test_corrupt_settings_shapes_are_controlled(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d+'/settings.json')
   for data in ('[]','null','{"R3_GEMINI_KEY":{"encrypted":[]}}','{"R3_GEMINI_KEY":{}}'):
    p.write_text(data)
    with self.assertRaises(SettingsError):Settings(p).load()
 def test_secret_not_plain_and_roundtrip(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d+'/settings.json');s=Settings(path,lambda b:bytes(x^91 for x in b),lambda b:bytes(x^91 for x in b))
   value={'R3_BLOG_ID':'123','R3_GEMINI_KEY':'test-api-secret-value'};s.save(value)
   self.assertNotIn('test-api-secret-value',path.read_text());self.assertEqual(s.load(),value)
 def test_plain_secret_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d+'/settings.json');p.write_text('{"R3_GEMINI_KEY":"plain"}')
   with self.assertRaises(SettingsError):Settings(p).load()
if __name__=='__main__':unittest.main()
