import json
import tempfile
import unittest
from r3studio.sync import Store,post_hash
from r3studio.apply import Apply
from r3studio.recovery import rollback_verified,reconcile_rollback,RecoveryHold
from test_apply_layout import Adapter
class RollbackAdapter(Adapter):
 def __init__(self):super().__init__();self.old=None;self.rollbacks=0
 def apply_update(self,plan):self.old=dict(self.post);return super().apply_update(plan)
 def rollback(self,*args):self.rollbacks+=1;self.post=dict(self.old,updated='v3')
class Tests(unittest.TestCase):
 def test_lost_rollback_reply_reconciles_without_second_restore(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,r=self.fixture(d);old=a.rollback
   def rollback(*args):old(*args);raise TimeoutError()
   a.rollback=rollback
   with self.assertRaises(TimeoutError):rollback_verified(s,a,r['audit_id'])
   a.request_status=lambda req:{'status':'DONE','action':'rollback','result':{'blogId':'blog','postId':'1','verified':True,'afterHash':post_hash(a.post)}}
   self.assertEqual(reconcile_rollback(s,a,r['audit_id'])['status'],'ROLLED_BACK');self.assertEqual(a.rollbacks,1);s.close()
 def test_later_edit_blocks_rollback_confirmation(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,r=self.fixture(d);old=a.rollback
   def rollback(*args):old(*args);raise TimeoutError()
   a.rollback=rollback
   with self.assertRaises(TimeoutError):rollback_verified(s,a,r['audit_id'])
   a.post['content']='later edit'
   a.request_status=lambda req:{'status':'DONE','action':'rollback','result':{'blogId':'blog','postId':'1','verified':True,'afterHash':post_hash(a.post)}}
   with self.assertRaises(RecoveryHold):reconcile_rollback(s,a,r['audit_id'])
   self.assertEqual(a.rollbacks,1);s.close()
 def test_failed_rollback_get_stays_unknown(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,r=self.fixture(d);old_get=a.get_post
   def get(pid):
    if a.rollbacks:raise TimeoutError()
    return old_get(pid)
   a.get_post=get
   with self.assertRaises(TimeoutError):rollback_verified(s,a,r['audit_id'])
   self.assertEqual(s.db.execute('SELECT status FROM apply_history').fetchone()[0],'ROLLBACK_NEEDS_RECONCILE');s.close()
 def fixture(self,d):
  s=Store(d+'/db');a=RollbackAdapter();p=Apply(s,a)
  r=p.apply(p.prepare('1','new','<p>'+('수정 내용 '*60)+'</p>'));return s,a,r
 def test_safe_rollback(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,r=self.fixture(d)
   self.assertEqual(rollback_verified(s,a,r['audit_id'])['status'],'ROLLED_BACK');self.assertEqual(a.post['title'],'old');s.close()
 def test_followup_edit_blocks_rollback(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,r=self.fixture(d);a.post['content']='someone else edited'
   with self.assertRaises(ValueError):rollback_verified(s,a,r['audit_id'])
   self.assertEqual(a.rollbacks,0);s.close()
if __name__=='__main__':unittest.main()
