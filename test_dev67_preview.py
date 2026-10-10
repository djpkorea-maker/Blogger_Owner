import io,tempfile,unittest
from pathlib import Path
from r3studio.preview import preview_parts,thumbnail_bytes
from r3studio.images import inspect_bytes

def pixels():
 from PIL import Image
 out=io.BytesIO();Image.new('RGB',(1024,576),'#90a0b0').save(out,format='PNG');return out.getvalue()
class Tests(unittest.TestCase):
 def test_image_position_alt_and_caption_are_preserved(self):
  html='<p>앞 문장</p><figure><img src="https://lh3.googleusercontent.com/a" alt="바퀴 &amp; 브러시"><figcaption>그림 1. 하부 점검 모습</figcaption></figure><p>뒷 문장</p>'
  parts=preview_parts(html);image=next(p for p in parts if p['kind']=='image');index=parts.index(image)
  self.assertIn('앞 문장',''.join(p.get('text','') for p in parts[:index]));self.assertIn('뒷 문장',''.join(p.get('text','') for p in parts[index+1:]))
  self.assertEqual(image['alt'],'바퀴 & 브러시');self.assertEqual(image['caption'],'그림 1. 하부 점검 모습')
 def test_pending_text_is_distinct_from_actual_html(self):
  review={'index':1,'url':'https://lh3.googleusercontent.com/a','suggested_text':{'alt':'수정 ALT','caption':'수정 설명'}}
  html='<figure><img src="https://lh3.googleusercontent.com/a" alt="기존 ALT"><figcaption>기존 설명</figcaption></figure>'
  image=next(p for p in preview_parts(html,[review],True) if p['kind']=='image')
  self.assertEqual(image['alt'],'기존 ALT');self.assertEqual(image['caption'],'기존 설명');self.assertEqual(image['pending_text']['alt'],'수정 ALT')
  self.assertNotIn('pending_text',next(p for p in preview_parts(html,[review]) if p['kind']=='image'))
 def test_applied_text_not_marked_pending_and_wrong_image_review_ignored(self):
  html='<figure><img src="a" alt="새 ALT"><figcaption>새 설명</figcaption></figure>'
  review={'index':1,'url':'a','suggested_text':{'alt':'새 ALT','caption':'새 설명'}}
  self.assertNotIn('pending_text',next(p for p in preview_parts(html,[review],True) if p['kind']=='image'))
  review['url']='different';review['suggested_text']['alt']='잘못된 대상'
  self.assertNotIn('pending_text',next(p for p in preview_parts(html,[review],True) if p['kind']=='image'))
 def test_scripts_hidden_and_ambiguous_caption_not_assumed(self):
  parts=preview_parts('<script>숨겨진 코드<img src="bad"></script><p>본문<img src="a" alt="점검 사진"><span>설명 문장</span></p>')
  self.assertEqual(sum(p['kind']=='image' for p in parts),1)
  self.assertNotIn('숨겨진 코드',''.join(p.get('text','') for p in parts))
  self.assertTrue(next(p for p in parts if p['kind']=='image')['caption_uncertain'])
 def test_cached_pixels_prevent_repeat_download(self):
  data=pixels();info=inspect_bytes(data)
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'image.image';path.write_bytes(data)
   def forbidden(u):raise AssertionError('중복 다운로드')
   thumbnail=thumbnail_bytes('https://lh3.googleusercontent.com/a',d,{'preview_file':str(path),'pixel_hash':info['pixel_hash']},forbidden)
   from PIL import Image
   with Image.open(io.BytesIO(thumbnail)) as im:self.assertLessEqual(im.width,420);self.assertLessEqual(im.height,260)
 def test_changed_cache_or_outside_path_requires_public_download(self):
  data=pixels();calls=[]
  def download(u):calls.append(u);return data
  with tempfile.TemporaryDirectory() as d,tempfile.TemporaryDirectory() as outside:
   path=Path(d)/'image.image';path.write_bytes(data)
   thumbnail_bytes('https://lh3.googleusercontent.com/a',d,{'preview_file':str(path),'pixel_hash':'different'},download)
   path=Path(outside)/'image.image';path.write_bytes(data)
   thumbnail_bytes('https://lh3.googleusercontent.com/b',d,{'preview_file':str(path),'pixel_hash':inspect_bytes(data)['pixel_hash']},download)
  self.assertEqual(len(calls),2)
if __name__=='__main__':unittest.main()
