import io
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from r3studio.images import inspect_bytes,ImageHold,ImageQA,validate_text
from r3studio.sync import Store
class Vision:
 model='vision-test'
 def __init__(self): self.calls=[]
 def image_object(self,prompt,data,mime):
  self.calls.append(data)
  if 'match:boolean' in prompt:return {'match':True}
  if 'caption:' in prompt:return {'alt':'작업대 위에 놓인 전자레인지','caption':'작업대 위에 놓인 전자레인지와 주변 공간을 보여주는 모습입니다.'}
  return dict(relevant=True,visual_quality=True,single_scene=True,no_overlay_text=True,safe_depiction=True,observed='작업대의 전자레인지')
def image():
 out=io.BytesIO();Image.new('RGB',(1024,576),(130,100,80)).save(out,format='PNG');return out.getvalue()
class Tests(unittest.TestCase):
 def test_bad_confirmation_is_hold_not_cached(self):
  class Bad(Vision):
   def image_object(self,prompt,data,mime):
    if 'match:boolean' in prompt:return ['incorrect']
    return super().image_object(prompt,data,mime)
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');p=Path(d+'/a.png');p.write_bytes(image())
   result,reused=ImageQA(s,Bad()).check(p,'제목','본문','blog','post')
   self.assertEqual(result['result'],'HOLD');self.assertFalse(reused)
   self.assertEqual(s.db.execute('SELECT COUNT(*) FROM image_qa_cache').fetchone()[0],0)
   self.assertEqual(s.db.execute('SELECT result FROM image_checks').fetchone()[0],'HOLD');s.close()
 def test_ai_failure_at_every_stage_records_safe_hold(self):
  from r3studio.ai import AIError
  for stage in (1,2,3):
   class Failed(Vision):
    def __init__(self):super().__init__();self.count=0
    def image_object(self,prompt,data,mime):
     self.count+=1
     if self.count==stage:raise AIError('sensitive remote response')
     return super().image_object(prompt,data,mime)
   with self.subTest(stage=stage),tempfile.TemporaryDirectory() as d:
    s=Store(d+'/db');p=Path(d+'/a.png');p.write_bytes(image());a=Failed()
    result,_=ImageQA(s,a).check(p,'제목','본문','blog','post')
    self.assertEqual(result['result'],'HOLD');self.assertEqual(a.count,stage)
    saved=s.db.execute('SELECT details FROM image_checks').fetchone()[0]
    self.assertNotIn('sensitive remote response',saved)
    self.assertEqual(s.db.execute('SELECT COUNT(*) FROM image_qa_cache').fetchone()[0],0);s.close()
 def test_corrupt(self):
  with self.assertRaises(ImageHold):inspect_bytes(b'not an image')
 def test_dimensions(self):
  out=io.BytesIO();Image.new('RGB',(200,200)).save(out,format='PNG')
  with self.assertRaises(ImageHold):inspect_bytes(out.getvalue())
 def test_pixels_and_cache_context(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');p=Path(d+'/a.png');p.write_bytes(image());ai=Vision();qa=ImageQA(s,ai)
   result,reused=qa.check(p,'전자레인지','본문','blog','post')
   self.assertEqual(result['result'],'PASS');self.assertFalse(reused);self.assertEqual(len(ai.calls),3)
   self.assertTrue(all(b==p.read_bytes() for b in ai.calls))
   self.assertTrue(qa.check(p,'전자레인지','본문','blog','post')[1]);self.assertEqual(len(ai.calls),3)
   qa.check(p,'김치냉장고','다른 본문','blog','post');self.assertEqual(len(ai.calls),6);s.close()
 def test_mismatch_no_alt(self):
  class Wrong(Vision):
   def image_object(self,prompt,data,mime):
    self.calls.append(data);return dict(relevant=False,visual_quality=True,single_scene=True,no_overlay_text=True,safe_depiction=True,observed='다른 장비')
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');p=Path(d+'/a.png');p.write_bytes(image());a=Wrong()
   r,_=ImageQA(s,a).check(p,'전자레인지','본문','blog','post')
   self.assertEqual(r['result'],'HOLD');self.assertNotIn('alt',r);self.assertEqual(len(a.calls),1);s.close()
 def test_caption_validation(self):
  with self.assertRaises(ImageHold):validate_text({'alt':'<script>bad</script>','caption':'설명문입니다. 또 다른 설명입니다.'})
 def test_rest_receives_inline_pixels(self):
  import base64,json
  from r3studio.ai import Gemini
  calls=[]
  def transport(payload):
   calls.append(payload)
   return {'steps':[{'type':'model_output','content':[{'type':'text','text':json.dumps({'match':True})}]}]}
  data=image();g=Gemini('not-real-key','test-model',transport)
  self.assertTrue(g.image_object('확인',data,'image/png')['match'])
  block=calls[0]['input'][1]
  self.assertEqual(base64.b64decode(block['data']),data);self.assertEqual(block['mime_type'],'image/png')
 def test_generation_image_checkpoint_stays_hold(self):
  import json
  from r3studio.generation import Generation
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');a=Vision();g=Generation(s,a,'blog')
   job=g.reserve('전자레인지 후보 이미지 테스트')
   g.save(job,'이미지 대기','HOLD',{'title':'전자레인지','content':'본문'})
   paths=[]
   for name in ('a.png','b.png'):
    p=Path(d)/name;p.write_bytes(image());paths.append(str(p))
   result=g.check_image_candidates(job,paths)
   self.assertEqual(result['status'],'HOLD');self.assertEqual(result['stage'],'이미지 배치·링크 대기')
   self.assertEqual(len(result['images']),2);s.close()
if __name__=='__main__':unittest.main()

