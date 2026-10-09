import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from r3studio.app import App
from r3studio.tasks import Cancellation
class Tests(unittest.TestCase):
 def test_preview_worker_never_sends_insert_or_publish(self):
  from test_publish_imagegen import Tests as Fixture,Adapter
  with tempfile.TemporaryDirectory() as d:
   s,g,job=Fixture().generation(d+'/studio.sqlite3');s.close();adapter=Adapter()
   app=App.__new__(App);app.base=Path(d);app.events=queue.Queue();app.cancel_token=Cancellation()
   values={'R3_BLOG_ID':'123','R3_BRIDGE_URL':'https://script.google.com/macros/s/abc/exec','R3_BRIDGE_SECRET':'key'}
   with patch.dict('os.environ',values),patch('r3studio.bridge.BridgeAdapter.from_environment',return_value=adapter):app.ai_worker('draft',job)
   events=[]
   while not app.events.empty():events.append(app.events.get())
   self.assertEqual(events[-1][0],'publication_ready');self.assertEqual(adapter.inserts,0);self.assertEqual(adapter.publishes,0)
if __name__=='__main__':unittest.main()
