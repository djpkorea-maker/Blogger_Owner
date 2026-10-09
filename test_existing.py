import tempfile
import unittest
from unittest.mock import patch
from r3studio.sync import Store,Sync
from r3studio.gates import Result,run_checks
from r3studio.existing import inspect_existing,record_incomplete
from r3studio.images import ImageHold
from test_generation import Fake,pack
class Adapter:
 blog_id='blog'
 def __init__(self):self.post={'id':'1','status':'SCHEDULED','updated':'v1','title':'예약 검사','content':'<p>'+('본문 내용 '*400)+'</p>','url':'https://example.com/p'};self.gets=0
 def list_metadata(self):return [{k:self.post[k] for k in ('id','status','updated')}]
 def get_post(self,pid):self.gets+=1;return dict(self.post)
class AI(Fake):
 def ask(self,*args,**kwargs):return {'citations':['https://example.com/source']}
class Tests(unittest.TestCase):
 def test_incomplete_recheck_replaces_old_pass_and_keeps_history(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');a=Adapter();Sync(s,a,'blog').run()
   s.db.execute('UPDATE posts SET grade="SCHEDULED_PASS"');s.db.commit()
   record_incomplete(s,'blog','1');run_checks(s,'blog')
   self.assertEqual(s.db.execute('SELECT grade FROM posts').fetchone()[0],'SCHEDULED_HOLD')
   self.assertTrue(s.db.execute('SELECT count(*) FROM recovery_checks').fetchone()[0]>=2);s.close()
 def run_case(self,image_error=False):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');a=Adapter();Sync(s,a,'blog').run()
   with patch('r3studio.existing.fast_check',return_value=Result('NEEDS_DEEP','DEEP',[],{})),patch('r3studio.existing.check_public_images',side_effect=ImageHold('이미지 보류') if image_error else None,return_value=[{'result':'PASS'},{'result':'PASS'}]),patch('r3studio.existing.check_links',return_value={'pass':True}):
    result=inspect_existing(s,a,AI(),'1',pack(),d)
   self.assertEqual(s.db.execute('SELECT grade FROM posts').fetchone()[0],result['grade'])
   run_checks(s,'blog');self.assertEqual(s.db.execute('SELECT grade FROM posts').fetchone()[0],result['grade'])
   if not image_error:
    s.db.execute('INSERT INTO posts(blog_id,post_id,title,status,updated,url,content,content_hash) VALUES(?,?,?,?,?,?,?,?)',('blog','2','새 글','LIVE','v1','https://example.com/new','새 본문','hash'));s.db.commit()
    run_checks(s,'blog');self.assertEqual(s.db.execute('SELECT grade FROM posts WHERE post_id="1"').fetchone()[0],'SCHEDULED_HOLD')
   s.close();return result
 def test_scheduled_pass_requires_all_checks(self):self.assertEqual(self.run_case()['grade'],'SCHEDULED_PASS')
 def test_failed_pixels_keep_scheduled_hold(self):self.assertEqual(self.run_case(True)['grade'],'SCHEDULED_HOLD')
if __name__=='__main__':unittest.main()
