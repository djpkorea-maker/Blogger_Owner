import tempfile
import unittest
from r3studio.start_mode import demo_on_start
from r3studio.settings import Settings,SettingsError
class Tests(unittest.TestCase):
 def test_absent_or_unknown_mode_always_uses_demo(self):
  self.assertTrue(demo_on_start({}));self.assertTrue(demo_on_start({'R3_START_MODE':'broken'}));self.assertFalse(demo_on_start({'R3_START_MODE':'LIVE'}))
 def test_mode_survives_settings_roundtrip(self):
  with tempfile.TemporaryDirectory() as d:
   settings=Settings(d+'/settings.json');settings.save({'R3_START_MODE':'LIVE'})
   self.assertFalse(demo_on_start(settings.load()))
   with self.assertRaises(SettingsError):settings.save({'R3_START_MODE':'unknown'})
if __name__=='__main__':unittest.main()
