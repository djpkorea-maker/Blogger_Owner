import unittest
from r3studio.captions import image_captions
from r3studio.images import ImageHold

class Tests(unittest.TestCase):
    def test_mixed_existing_formats(self):
        content='<figure><img src="a"><figcaption>그림 1. <b>첫 이미지</b></figcaption></figure><div class="separator"><a><img src="b" /></a></div>\n<div class="abs-v23-caption">그림 2. 둘째 &amp; 이미지</div>'
        self.assertEqual(image_captions(content),['그림 1. 첫 이미지','그림 2. 둘째 & 이미지'])
    def test_unrelated_caption_cannot_supply_missing_one(self):
        for content in ['<img src="a"><figcaption>별도 설명</figcaption>', '<figure><img src="a"></figure><figure><figcaption>별도 설명</figcaption></figure>', '<div class="separator"><img></div><p>본문</p><div class="abs-v23-caption">설명</div>']:
            with self.subTest(content=content),self.assertRaises(ImageHold):image_captions(content)
    def test_ambiguous_or_empty_caption_holds(self):
        for content in ['<figure><img><img><figcaption>설명</figcaption></figure>', '<figure><img><figcaption>설명</figcaption><figcaption>중복</figcaption></figure>', '<figure><img><figcaption> </figcaption></figure>']:
            with self.subTest(content=content),self.assertRaises(ImageHold):image_captions(content)
