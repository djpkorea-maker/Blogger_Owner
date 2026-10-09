import unittest
from build_preflight import inspect

class Tests(unittest.TestCase):
    def test_linux_does_not_claim_windows_build_ready(self):
        report=inspect('Linux',(3,12),lambda name:object(),lambda name:'node')
        self.assertEqual(report['missing'],['windows']);self.assertFalse(report['ready_to_attempt_build'])
    def test_windows_dependencies_and_validation_are_separate(self):
        ready=inspect('Windows',(3,12),lambda name:object(),lambda name:'node')
        self.assertTrue(ready['ready_to_attempt_build']);self.assertFalse(ready['windows_execution_verified'])
        missing=inspect('Windows',(3,12),lambda name:None if name=='PyInstaller' else object(),lambda name:None)
        self.assertEqual(missing['missing'],['pyinstaller','node'])
