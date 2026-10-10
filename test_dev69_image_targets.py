import io,json,tempfile,unittest
from pathlib import Path
from PIL import Image
import test_dev68_repair_images as fixture
from test_images import Vision,image
from r3studio.repair_images import RepairImages
from r3studio.images import ImageHold,inspect_bytes
class Targets(unittest.TestCase):
 def setup(self,d):return fixture.Tests().setup_case(d)
 def test_each_slot_sends_its_own_actual_pixels_to_all_three_ai_checks(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid,c=self.setup(d);out=io.BytesIO();Image.new('RGB',(1024,576),'blue').save(out,format='PNG')
   data={'https://lh3.googleusercontent.com/a':image(),'https://lh3.googleusercontent.com/b':out.getvalue()};ai=Vision();svc=RepairImages(s,a,ai,d)
   for slot,url in enumerate(data,1):
    start=len(ai.calls);r=svc.operate(pid,'alt',slot,download=data.__getitem__)
    candidate=r['image_edit_candidates'][str(slot)]
    self.assertEqual(candidate['target']['slot'],slot);self.assertEqual(candidate['target']['url'],url)
    self.assertEqual(ai.calls[start:],[data[url]]*3)
   s.close()
 def test_candidate_moved_to_other_slot_is_blocked(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid,c=self.setup(d);svc=RepairImages(s,a,Vision(),d);r=svc.operate(pid,'alt',1,download=lambda u:image())
   row,p=svc.load(pid);p['image_edit_candidates']['2']=p['image_edit_candidates']['1'];svc.save(pid,p)
   with self.assertRaisesRegex(ImageHold,'이미지 번호'):svc.operate(pid,'choose',2)
   s.close()
 def test_same_pixels_in_two_new_candidates_are_not_accepted(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid,c=self.setup(d);svc=RepairImages(s,a,Vision(),d)
   svc.operate(pid,'import',1,path=c['file']);r=svc.operate(pid,'import',2,path=c['file'])
   self.assertEqual(r['image_edit_candidates']['2']['result'],'HOLD')
   with self.assertRaises(ImageHold):svc.operate(pid,'choose',2)
   s.close()
