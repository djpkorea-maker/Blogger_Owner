import json
import tempfile
import unittest
from r3studio.sync import Store,now,post_hash
from r3studio.apply import Apply
from r3studio.recovery import rollback_verified,reconcile_rollback

class NoRemote:
    blog_id='blog'
    def __getattr__(self,name):raise AssertionError('Remote access must not occur: '+name)

class Tests(unittest.TestCase):
    def test_corrupt_and_mismatched_records_block_before_remote(self):
        before={'id':'wrong','title':'제목','content':'본문','status':'LIVE','updated':'v1','url':'https://example.org/p'}
        wrong={'post_id':'wrong','blog_id':'blog','before':before,'expected_hash':post_hash(before),'expected_updated':'v1','expected_url':before['url'],'proposal':{'title':'제목','content':'수정 본문','labels':[]},'request_id':'req'}
        for raw in ('broken','[]',json.dumps(wrong)):
            for status,action in [('NEEDS_RECONCILE',lambda s,a,i:Apply(s,a).reconcile(i)),('VERIFIED',rollback_verified),('ROLLBACK_NEEDS_RECONCILE',reconcile_rollback)]:
                with self.subTest(raw=raw,status=status),tempfile.TemporaryDirectory() as d:
                    store=Store(d+'/db')
                    with store.db:
                        audit=store.db.execute('INSERT INTO apply_history(blog_id,post_id,created_at,expected_hash,actual_hash,status,backup_ref,details) VALUES(?,?,?,?,?,?,?,?)',('blog','target',now(),'hash','hash',status,'backup',raw)).lastrowid
                    with self.assertRaises(ValueError):action(store,NoRemote(),audit)
                    self.assertEqual(store.db.execute('SELECT status FROM apply_history').fetchone()[0],status)
                    store.close()
    def test_inconsistent_baseline_blocks_apply(self):
        before={'id':'target','title':'제목','content':'본문','status':'LIVE','updated':'v1','url':'https://example.org/p'}
        plan={'post_id':'target','blog_id':'blog','before':before,'expected_hash':'wrong-hash','expected_updated':'v1','expected_url':before['url'],'proposal':{'title':'제목','content':'수정 본문','labels':[]},'request_id':'req'}
        with tempfile.TemporaryDirectory() as d:
            store=Store(d+'/db')
            with self.assertRaises(ValueError):Apply(store,NoRemote()).apply(plan)
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM apply_history').fetchone()[0],0);store.close()
