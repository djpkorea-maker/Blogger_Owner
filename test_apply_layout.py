import copy
import unittest
import tempfile
from r3studio.sync import Store,post_hash
from r3studio.apply import Apply
from r3studio.layout import compose,LayoutHold
class Adapter:
 blog_id='blog'
 def __init__(self):self.post={'id':'1','title':'old','content':'<p>old</p>','status':'LIVE','labels':['a'],'updated':'v1','url':'https://example.com/p'};self.writes=0;self.timeout=False
 def get_post(self,pid):return copy.deepcopy(self.post)
 def apply_update(self,plan):
  self.writes+=1
  if self.timeout:raise TimeoutError('lost response')
  self.post.update(plan['proposal']);self.post['updated']='v2';return {'backupFileId':'backup'}
class Tests(unittest.TestCase):
 def test_proposal_mutation_blocks_before_remote_read(self):
  for field,value in [('title','검토 후 다른 제목'),('content','<p>'+('다른 본문 '*100)+'</p>'),('labels',['변경'])]:
   with self.subTest(field=field),tempfile.TemporaryDirectory() as d:
    s=Store(d+'/db');a=Adapter();p=Apply(s,a);plan=p.prepare('1','new','<p>'+('본문 '*100)+'</p>')
    plan['proposal'][field]=value
    def forbidden(pid):raise AssertionError('Changed plan must stop before GET')
    a.get_post=forbidden
    with self.assertRaisesRegex(ValueError,'계획 변경'):p.apply(plan)
    self.assertEqual(a.writes,0);self.assertEqual(s.db.execute('SELECT COUNT(*) FROM apply_history').fetchone()[0],0);s.close()
 def test_url_change_blocks_before_audit_and_patch(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');a=Adapter();p=Apply(s,a);plan=p.prepare('1','new','<p>'+('본문 '*100)+'</p>')
   a.post['url']='https://example.com/new-address'
   with self.assertRaisesRegex(ValueError,'주소 변경'):p.apply(plan)
   self.assertEqual(a.writes,0);self.assertEqual(s.db.execute('SELECT COUNT(*) FROM apply_history').fetchone()[0],0);s.close()
 def test_corrupt_related_proposal_does_not_undo_verified_audit(self):
  import json
  from r3studio.sync import now
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db')
   class Lost(Adapter):
    def apply_update(self,plan):super().apply_update(plan);raise TimeoutError()
    def request_status(self,r):return {'status':'DONE','action':'apply_update','result':{'blogId':'blog','postId':'1','verified':True,'backupFileId':'backup','afterHash':post_hash(self.post)}}
   a=Lost();p=Apply(s,a);plan=p.prepare('1','new','<p>'+('본문 '*100)+'</p>')
   with self.assertRaises(TimeoutError):p.apply(plan)
   s.db.execute('CREATE TABLE repair_proposals(id INTEGER PRIMARY KEY,blog_id TEXT,post_id TEXT,created_at TEXT,status TEXT,payload TEXT)')
   for raw in ('broken',json.dumps({'plan':plan})):
    s.db.execute('INSERT INTO repair_proposals(blog_id,post_id,created_at,status,payload) VALUES(?,?,?,?,?)',('blog','1',now(),'NEEDS_RECONCILE',raw))
   s.db.commit();result=p.reconcile(1)
   self.assertEqual(result['unreadable_related_records'],1);self.assertEqual(a.writes,1)
   self.assertEqual(s.db.execute('SELECT status FROM apply_history').fetchone()[0],'VERIFIED')
   self.assertEqual([r[0] for r in s.db.execute('SELECT status FROM repair_proposals ORDER BY id')],['NEEDS_RECONCILE','APPLIED']);s.close()
 def test_reconcile_modified_post_without_second_patch(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db')
   class Lost(Adapter):
    def apply_update(self,plan):super().apply_update(plan);raise TimeoutError()
    def request_status(self,r):return {'status':'DONE','action':'apply_update','result':{'blogId':'blog','postId':'1','verified':True,'backupFileId':'backup','afterHash':post_hash(self.post)}}
   a=Lost();p=Apply(s,a)
   with self.assertRaises(TimeoutError):p.apply(p.prepare('1','new','<p>'+('본문 '*100)+'</p>'))
   result=p.reconcile(1);self.assertEqual(result['status'],'VERIFIED');self.assertEqual(a.writes,1);s.close()
 def test_reconcile_rejects_later_edit(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');a=Adapter();a.timeout=True;p=Apply(s,a)
   with self.assertRaises(TimeoutError):p.apply(p.prepare('1','new','<p>'+('본문 '*100)+'</p>'))
   a.request_status=lambda r:{'status':'DONE','action':'apply_update','result':{'blogId':'blog','postId':'1','verified':True,'backupFileId':'backup','afterHash':post_hash(a.post)}}
   with self.assertRaises(ValueError):p.reconcile(1)
   self.assertEqual(a.writes,1);s.close()
 def test_stale_blocks_write(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');a=Adapter();p=Apply(s,a);plan=p.prepare('1','new','<h2>확인</h2><p>'+('새 본문 '*60)+'</p>')
   a.post['content']='someone edited'
   with self.assertRaises(ValueError):p.apply(plan)
   self.assertEqual(a.writes,0);s.close()
 def test_verified(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');a=Adapter();p=Apply(s,a)
   self.assertEqual(p.apply(p.prepare('1','new','<h2>확인</h2><p>'+('새 본문 '*60)+'</p>'))['status'],'VERIFIED')
   self.assertEqual(a.post['labels'],['a']);self.assertEqual(a.writes,1);s.close()
 def test_no_blind_retry(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');a=Adapter();a.timeout=True;p=Apply(s,a)
   with self.assertRaises(TimeoutError):p.apply(p.prepare('1','new','<p>'+('새 본문 '*60)+'</p>'))
   self.assertEqual(a.writes,1);self.assertEqual(s.db.execute('SELECT status FROM apply_history').fetchone()[0],'NEEDS_RECONCILE');s.close()
 def test_layout_escape_and_receipt(self):
  candidate={'result':'PASS','info':{'byte_hash':'abc'},'alt':'용기 "모양"','caption':'전자레인지 용기의 형태를 보여줍니다.'}
  receipt={'ok':True,'publicImageUrl':'https://lh3.googleusercontent.com/d/example=w1024','byte_hash':'abc'}
  output=compose('<h2>순서</h2><p>내용</p><h2>조건</h2><p>내용2</p>',[candidate,candidate],[receipt,receipt])
  self.assertIn('&quot;',output);self.assertEqual(output.count('<figure '),2)
  receipt['byte_hash']='wrong'
  with self.assertRaises(LayoutHold):compose('<h2>순서</h2><h2>조건</h2>',[candidate,candidate],[receipt,receipt])
 def test_active_html_blocked(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');p=Apply(s,Adapter())
   with self.assertRaises(ValueError):p.prepare('1','제목','<script>bad()</script><p>'+('내용 '*100)+'</p>')
   s.close()
if __name__=='__main__':unittest.main()

