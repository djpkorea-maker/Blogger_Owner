import json
import tempfile
import unittest
from r3studio.images import check_public_images,ImageHold
from r3studio.ai import AIError
from r3studio.sync import Store
from test_images import Vision,image

CONTENT='<div class="separator"><img src="https://lh3.googleusercontent.com/a" alt="전자레인지"></div><div class="abs-v23-caption">그림 1. 작업대 위 전자레인지</div><figure><img src="https://lh3.googleusercontent.com/b" alt="작업대"><figcaption>그림 2. 주변 작업 공간</figcaption></figure>'

class Tests(unittest.TestCase):
    def test_legacy_and_current_captions_reach_pixel_confirmation(self):
        class Observer(Vision):
            def __init__(self):super().__init__();self.confirmations=[]
            def image_object(self,prompt,data,mime):
                if '이 ALT와 설명문이 모두' in prompt:
                    self.confirmations.append(json.loads(prompt.split('\n',1)[1]))
                return super().image_object(prompt,data,mime)
        with tempfile.TemporaryDirectory() as d:
            store=Store(d+'/db');ai=Observer();downloads=[];pixels=image()
            def download(url):downloads.append(url);return pixels
            results=check_public_images(store,ai,'제목',CONTENT,d,'blog','post',download)
            self.assertEqual(len(results),2)
            self.assertEqual([x['caption'] for x in ai.confirmations],['그림 1. 작업대 위 전자레인지','그림 2. 주변 작업 공간'])
            self.assertEqual([x['alt'] for x in ai.confirmations],['전자레인지','작업대'])
            self.assertTrue(all(data==pixels for data in ai.calls))
            self.assertEqual(len(downloads),2);store.close()
    def test_final_confirmation_failure_never_returns_pass(self):
        for failure in ('ai_error','wrong_shape','mismatch'):
            class Failed(Vision):
                def image_object(self,prompt,data,mime):
                    if '이 ALT와 설명문이 모두' in prompt:
                        if failure=='ai_error':raise AIError('private response')
                        return [] if failure=='wrong_shape' else {'match':False}
                    return super().image_object(prompt,data,mime)
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as d:
                store=Store(d+'/db')
                with self.assertRaises(ImageHold) as caught:
                    check_public_images(store,Failed(),'제목',CONTENT,d,'blog','post',lambda url:image())
                self.assertNotIn('private response',str(caught.exception));store.close()
    def test_missing_images_or_alt_stops_before_download_and_ai(self):
        for content in ('<p>이미지 없음</p>',CONTENT.replace('alt="작업대"','alt=" "')):
            with self.subTest(content=content),tempfile.TemporaryDirectory() as d:
                store=Store(d+'/db');ai=Vision();downloads=[]
                with self.assertRaises(ImageHold):
                    check_public_images(store,ai,'제목',content,d,'blog','post',lambda url:downloads.append(url))
                self.assertEqual(ai.calls,[]);self.assertEqual(downloads,[]);store.close()
