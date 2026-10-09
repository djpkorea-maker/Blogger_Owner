import tempfile
import unittest
from pathlib import Path
from release_check import inspect
from test_sync import Adapter

class Tests(unittest.TestCase):
    def test_read_only_smoke_checks_cache_without_claiming_release(self):
        adapter=Adapter();adapter.blog_id='test'
        with tempfile.TemporaryDirectory() as d:
            result=inspect(adapter,'MOCK',str(Path(d)/'db'))
        self.assertEqual(result['first_sync']['changed'],3)
        self.assertEqual(result['second_sync']['reused'],3)
        self.assertEqual(adapter.gets,3)
        self.assertFalse(result['writes_performed']);self.assertFalse(result['ai_calls_performed'])
        self.assertFalse(result['full_release_verified']);self.assertFalse(result['windows_gui_verified'])
