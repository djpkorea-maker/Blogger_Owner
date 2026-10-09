import copy
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from r3studio.images import inspect_bytes
from r3studio.layout import reconcile_uploads,LayoutHold

class Generation:
 def __init__(self,payload):self.payload=payload;self.composed=0
 def load_job(self,job):return {'payload':copy.deepcopy(self.payload)}
 def save(self,job,stage,status,payload):self.payload=copy.deepcopy(payload)
 def compose_uploaded(self,job,receipts):self.composed+=1;return {'status':'HOLD','job_id':job}

class Tests(unittest.TestCase):
 def fixture(self,d):
  path=Path(d)/'image.png';Image.new('RGB',(1024,576),(110,120,130)).save(path)
  info=inspect_bytes(path.read_bytes());candidate={'result':'PASS','file':str(path),'info':info,'alt':'장면','caption':'확인한 장면입니다.'}
  g=Generation({'image_candidates':[candidate,candidate],'upload_requests':[{'id':'r1','status':'SENDING','byte_hash':info['byte_hash']},{'id':'r2','status':'SENDING','byte_hash':info['byte_hash']}]})
  class Adapter:
   blog_id='blog'
   def request_status(self,r):return {'status':'DONE','action':'upload_image','result':{'ok':True,'blogId':'blog','byte_hash':info['byte_hash'],'publicImageUrl':'https://lh3.googleusercontent.com/d/'+r+'=w1024'}}
   def upload_image(self,*args):raise AssertionError('재업로드 금지')
  return g,Adapter()
 def test_recover_receipts_without_upload_or_article_pass(self):
  with tempfile.TemporaryDirectory() as d:
   g,a=self.fixture(d);r=reconcile_uploads(g,a,1)
   self.assertEqual(r['status'],'HOLD');self.assertEqual(g.composed,1)
   self.assertEqual(len(g.payload['upload_receipts']),2)
   self.assertTrue(all(not x['public_pixel_verified'] for x in g.payload['upload_receipts']))
 def test_wrong_server_bytes_are_not_adopted(self):
  with tempfile.TemporaryDirectory() as d:
   g,a=self.fixture(d);old=a.request_status
   def bad(r):
    out=old(r);out['result']['byte_hash']='wrong';return out
   a.request_status=bad
   with self.assertRaises(LayoutHold):reconcile_uploads(g,a,1)
   self.assertEqual(g.composed,0);self.assertNotIn('upload_receipts',g.payload)
if __name__=='__main__':unittest.main()
