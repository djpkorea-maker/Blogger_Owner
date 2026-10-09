import copy
import tempfile
import unittest
from r3studio.sync import Store,Sync,post_hash,guard_apply
class Adapter:
    def __init__(self):
        self.posts={str(i):{'id':str(i),'status':s,'updated':'v1','title':'제목','content':'<p>본문</p>'} for i,s in enumerate(['LIVE','SCHEDULED','DRAFT'])}; self.gets=0; self.fail=False
    def list_metadata(self):
        if self.fail: raise RuntimeError('network failed')
        return [{k:p[k] for k in ('id','status','updated')} for p in self.posts.values()]
    def get_post(self,pid): self.gets+=1; return copy.deepcopy(self.posts[pid])
class Tests(unittest.TestCase):
    def test_metadata_changes_without_updated_change(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(d+'/test.db'); a=Adapter()
            a.list_metadata=lambda: [{k:p.get(k,'') for k in ('id','status','updated','title','url')} for p in a.posts.values()]
            sync=Sync(store,a,'blog'); sync.run()
            for field,value in [('title','변경된 제목'),('url','https://example.org/new')]:
                a.posts['0'][field]=value
                self.assertEqual(sync.run(),{'listed':3,'changed':1,'reused':2})
                row=store.db.execute("SELECT * FROM posts WHERE post_id='0'").fetchone()
                self.assertEqual(row[field],value)
            self.assertEqual(a.gets,5)
            self.assertEqual(sync.run()['reused'],3)
            store.close()
    def test_metadata_body_race_preserves_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(d+'/test.db'); a=Adapter(); sync=Sync(store,a,'blog'); sync.run()
            before=[tuple(row) for row in store.db.execute('SELECT * FROM posts ORDER BY post_id')]
            a.posts['0']['title']='새 제목'
            a.list_metadata=lambda: [{k:p.get(k,'') for k in ('id','status','updated','title','url')} for p in a.posts.values()]
            original=a.get_post
            def raced(pid):
                post=original(pid); post['url']='https://example.org/raced'; return post
            a.get_post=raced
            with self.assertRaises(ValueError): sync.run()
            self.assertEqual([tuple(row) for row in store.db.execute('SELECT * FROM posts ORDER BY post_id')],before)
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM post_versions').fetchone()[0],3)
            store.close()
    def test_sync(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(d+'/test.db'); adapter=Adapter(); sync=Sync(store,adapter,'blog')
            self.assertEqual(sync.run(),{'listed':3,'changed':3,'reused':0})
            self.assertEqual(sync.run()['reused'],3); self.assertEqual(adapter.gets,3)
            adapter.posts['0'].update(updated='v2',title='새 제목')
            self.assertEqual(sync.run()['changed'],1); self.assertEqual(adapter.gets,4)
            adapter.fail=True
            with self.assertRaises(RuntimeError): sync.run()
            self.assertEqual(store.db.execute('SELECT SUM(present) FROM posts').fetchone()[0],3)
            adapter.fail=False; del adapter.posts['2']; sync.run()
            self.assertEqual(store.db.execute('SELECT SUM(present) FROM posts').fetchone()[0],2)
            store.close()
    def test_conflict(self):
        p={'title':'old','content':'body','status':'LIVE'}; h=post_hash(p)
        guard_apply(h,p); p['content']='new'
        with self.assertRaises(ValueError): guard_apply(h,p)
    def test_race(self):
        with tempfile.TemporaryDirectory() as d:
            store=Store(d+'/test.db'); a=Adapter()
            original=a.get_post
            def raced(pid):
                p=original(pid); p['updated']='v2'; return p
            a.get_post=raced
            with self.assertRaises(ValueError): Sync(store,a,'blog').run()
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM posts').fetchone()[0],0); store.close()
if __name__=='__main__': unittest.main()
