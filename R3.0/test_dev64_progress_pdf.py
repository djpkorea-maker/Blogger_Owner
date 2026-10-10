import io,json,tempfile,unittest
from unittest.mock import patch
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject,NameObject,DictionaryObject
from r3studio.sources import SourceReader
from r3studio.sync import Store
from r3studio.progress import StageProgress,progress_state
from r3studio.evidence import Research,EvidenceHold
from test_generation import pack

def pdf_bytes():
 w=PdfWriter();page=w.add_blank_page(width=500,height=500)
 font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
 page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):w._add_object(font)})})
 stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 20 400 Td ('+b'Motor current and stall protection. '*8+b') Tj ET')
 page[NameObject('/Contents')]=w._add_object(stream);out=io.BytesIO();w.write(out);return out.getvalue()
class Tests(unittest.TestCase):
 def test_waiting_and_retry_do_not_blink_or_reverse_stage(self):
  p=StageProgress();values=[p.update(t) for t in ['Blogger 조회 3/3','근거 검색 1/3','근거 장부 작성 1/3','근거 장부 작성 · AI 응답 대기 중','근거 검색 2/3','근거 원문 확인 1/8','근거 원문 확인 8/8','이미지별 실제 픽셀·ALT 검사 1/2']]
  self.assertEqual(values,sorted(values));self.assertLess(values[-1],9)
  self.assertEqual(progress_state('AI 응답 대기')['mode'],'determinate')
 def test_pdf_original_is_extracted_and_cached(self):
  s=Store(':memory:');calls=[]
  def fetch(u):calls.append(u);return {'status':200,'url':u,'headers':{'Content-Type':'application/pdf'},'body':'','body_bytes':pdf_bytes()}
  reader=SourceReader(s,fetch);result=reader.read('https://official.example/manual.pdf')
  self.assertEqual(result['status'],'FETCHED');self.assertIn('Motor current',result['text']);reader.read(result['url']);self.assertEqual(len(calls),1);s.close()
 def test_broken_pdf_is_unavailable_not_false_evidence(self):
  s=Store(':memory:');reader=SourceReader(s,lambda u:{'status':200,'url':u,'headers':{'Content-Type':'application/pdf'},'body':'','body_bytes':b'not a pdf'})
  result=reader.read('https://official.example/manual.pdf');self.assertEqual(result['status'],'UNAVAILABLE');self.assertIn('PDF',result['reason']);s.close()
 def test_original_timeout_is_distinct(self):
  s=Store(':memory:')
  def fetch(u):raise TimeoutError()
  self.assertIn('시간 초과',SourceReader(s,fetch).read('https://a.example')['reason']);s.close()
 def test_research_cannot_add_new_numbers_to_article_claims(self):
  class AI:
   def ask(self,*a,**k):return {'citations':[{'url':s['url']} for s in pack()['sources']]}
   def object(self,prompt):
    p=pack()
    for f in p['facts']:f.update(article_excerpt='모터 전류를 측정하여 과부하를 감지합니다.',text='구속 전류는 정상 전류의 10배입니다.')
    return p
  result=Research(AI()).collect('title','topic',article='<p>모터 전류를 측정하여 과부하를 감지합니다.</p>')
  self.assertTrue(all('10배' not in f['text'] for f in result['facts']))
 def test_absent_article_excerpt_retries_without_extra_search(self):
  class AI:
   searches=0;formats=0
   def ask(self,*a,**k):self.searches+=1;return {'citations':[{'url':s['url']} for s in pack()['sources']]}
   def object(self,prompt):self.formats+=1;return pack()
  ai=AI()
  with self.assertRaises(EvidenceHold):Research(ai).collect('title','topic',article='<p>모터 전류를 측정하여 과부하를 감지합니다.</p>')
  self.assertEqual((ai.searches,ai.formats),(1,3))
if __name__=='__main__':unittest.main()
