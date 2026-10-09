import tempfile
import unittest
from r3studio.bridge import BridgeAdapter,BridgeError
from r3studio.gates import fast_check,run_checks
from r3studio.sync import Store,Sync
from r3studio.app import DemoAdapter
class Tests(unittest.TestCase):
    def test_reused_fast_result_replaces_unbacked_pass_display(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(d+'/db');Sync(store,DemoAdapter(),'demo').run();run_checks(store,'demo')
            store.db.execute('UPDATE posts SET grade="PASS"');store.db.commit()
            self.assertEqual(run_checks(store,'demo')['reused'],3)
            grades={r[0]:r[1] for r in store.db.execute('SELECT post_id,grade FROM posts')}
            self.assertEqual(grades,{'1':'NEEDS_DEEP','2':'SCHEDULED_HOLD','3':'EMPTY_BOTH'});store.close()
    def test_one_corrupt_fast_record_rechecks_only_that_post(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(d+'/db');Sync(store,DemoAdapter(),'demo').run();run_checks(store,'demo')
            store.db.execute('UPDATE recovery_checks SET details=? WHERE post_id=?',('bad-json','1'));store.db.commit()
            result=run_checks(store,'demo')
            self.assertEqual(result['checked'],1);self.assertEqual(result['reused'],2)
            self.assertEqual(run_checks(store,'demo')['reused'],3);store.close()
    def test_corrupt_deep_record_does_not_restore_pass(self):
        from r3studio.sync import now
        with tempfile.TemporaryDirectory() as d:
            store=Store(d+'/db');Sync(store,DemoAdapter(),'demo').run();run_checks(store,'demo')
            row=store.db.execute('SELECT content_hash FROM posts WHERE post_id="1"').fetchone()
            with store.db:store.db.execute('INSERT INTO recovery_checks(blog_id,post_id,content_hash,engine_version,checked_at,grade,details) VALUES(?,?,?,?,?,?,?)',('demo','1',row[0],'R3.0-existing-0.23',now(),'PASS','[]'))
            run_checks(store,'demo')
            self.assertEqual(store.db.execute('SELECT grade FROM posts WHERE post_id="1"').fetchone()[0],'NEEDS_DEEP');store.close()
    def adapter(self,fn): return BridgeAdapter('https://script.google.com/macros/s/EXAMPLE/exec','test-secret','blog',fn)
    def test_paginated_all_states(self):
        calls=[]
        def transport(body):
            p=body['payload']; calls.append(p)
            state=p['status']; token=p['pageToken']
            return {'ok':True,'blogId':'blog','status':state,'items':[{'id':state+token,'status':state,'updated':'v1'}],'nextPageToken':'p2' if state=='LIVE' and not token else ''}
        self.assertEqual(len(self.adapter(transport).list_metadata()),4); self.assertEqual(len(calls),4)
    def test_repeated_page(self):
        def fn(b): return {'ok':True,'blogId':'blog','status':'LIVE','items':[],'nextPageToken':'repeat'}
        with self.assertRaises(BridgeError): self.adapter(fn).list_metadata()
    def test_wrong_blog(self):
        with self.assertRaises(BridgeError): self.adapter(lambda b:{'ok':True,'blogId':'wrong'}).get_post('1')
    def test_gate_not_false_pass(self):
        p=DemoAdapter().get_post('1'); result=fast_check(p)
        self.assertNotIn(result.grade,('PASS','SCHEDULED_PASS')); self.assertFalse(result.verified)
    def test_empty_and_schedule(self):
        self.assertEqual(fast_check(DemoAdapter().get_post('3')).grade,'EMPTY_BOTH')
        self.assertEqual(fast_check(DemoAdapter().get_post('2')).grade,'SCHEDULED_HOLD')
    def test_gate_cache(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(d+'/db'); a=DemoAdapter(); Sync(store,a,'demo').run()
            self.assertEqual(run_checks(store,'demo')['checked'],3)
            self.assertEqual(run_checks(store,'demo')['reused'],3)
            a.posts[0]['updated']='2026-10-09T10:00:00Z'; a.posts[0]['content']+='<p>수정 내용</p>'
            Sync(store,a,'demo').run()
            result=run_checks(store,'demo')
            self.assertEqual(result['checked'],1); self.assertEqual(result['reused'],2)
            store.close()
if __name__=='__main__': unittest.main()
