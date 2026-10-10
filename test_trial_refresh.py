import json
import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from r3studio.sync import Store,Sync
from r3studio.gates import run_checks,fast_check
from r3studio.existing import record_incomplete
from r3studio.presentation import inspection_text
from r3studio.tasks import Cancellation
from test_sync import Adapter

class TrialRefreshTests(unittest.TestCase):
 def test_all_bodies_refetched_without_marking_unchanged_as_changed(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');a=Adapter();sync=Sync(s,a,'blog',force_refresh=True)
   sync.run();result=sync.run()
   self.assertEqual(a.gets,6);self.assertEqual(result['changed'],0)
   self.assertEqual(result['refetched'],3);self.assertEqual(result['reused'],0)
   self.assertEqual(s.db.execute('SELECT count(*) FROM post_versions').fetchone()[0],3);s.close()
 def test_same_timestamp_body_change_detected_in_trial(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');a=Adapter();sync=Sync(s,a,'blog',force_refresh=True);sync.run()
   a.posts['0']['content']='<p>새로운 본문</p>'
   self.assertEqual(sync.run()['changed'],1)
   self.assertEqual(s.db.execute('SELECT content FROM posts WHERE post_id="0"').fetchone()[0],'<p>새로운 본문</p>');s.close()
 def test_force_recheck_does_not_reuse_fast(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');a=Adapter();Sync(s,a,'blog').run();run_checks(s,'blog')
   with patch('r3studio.gates.fast_check',wraps=fast_check) as check:
    result=run_checks(s,'blog',force_recheck=True)
   self.assertEqual(check.call_count,3);self.assertEqual(result['reused'],0);self.assertEqual(result['checked'],3);s.close()
 def test_trial_worker_repeats_even_after_program_restart(self):
  from r3studio.app import App
  with tempfile.TemporaryDirectory() as d:
   for attempt in range(2):
    app=App.__new__(App);app.base=Path(d);app.events=queue.Queue();app.cancel_token=Cancellation();app.worker(True,force=True)
    events=[]
    while not app.events.empty():events.append(app.events.get())
    done=events[-1];self.assertEqual(done[0],'done')
    self.assertEqual(done[1]['refetched'],3);self.assertEqual(done[2]['checked'],3);self.assertEqual(done[2]['reused'],0)
 def test_failure_keeps_matching_fast_measurements(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');a=Adapter();Sync(s,a,'blog').run();run_checks(s,'blog')
   record=record_incomplete(s,'blog','0')
   text=inspection_text({'post_id':'0','status':'LIVE','grade':'NEEDS_DEEP','details':record})
   self.assertIn('본문 2자',text);self.assertNotIn('본문 ?자',text);s.close()
if __name__=='__main__':unittest.main()
