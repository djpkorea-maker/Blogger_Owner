import json
import tempfile
import unittest
from r3studio.ai import Gemini,AIError
from r3studio.evidence import validate_pack,EvidenceHold,Research
from r3studio.deep import evaluate
from r3studio.generation import Generation
from r3studio.sync import Store,Sync
from r3studio.app import DemoAdapter

def pack():
 result={'sources':[{'id':'s1','url':'https://manufacturer.example/manual','grade':'A'},{'id':'s2','url':'https://agency.example/guide','grade':'A'}],'facts':[{'id':str(i),'text':'조건을 확인한다 '+str(i),'source_ids':['s1' if i%2 else 's2'],'core':i<2,'kind':['core','core','practical','condition'][i]} for i in range(4)]}
 from r3studio.sync import now,digest
 quote='테스트 원문에서 확인한 안전 조건입니다.'
 result['original_verification']={'checked_at':now(),'pack_hash':digest({'sources':result['sources'],'facts':result['facts']}),'trusted_sources':['s1','s2'],'originals':{source['id']:{'status':'FETCHED','text':quote,'text_hash':digest(quote),'final_url':source['url']} for source in result['sources']},'claims':[{'fact_id':fact['id'],'source_id':fact['source_ids'][0],'supported':True,'quote':quote} for fact in result['facts']]}
 return result
class Fake:
 model='test'
 def object(self,prompt): return {'fact':'PASS','safety':'PASS','intent':'PASS','practical_value':'PASS','originality':'PASS','score':95,'severity':'none','issues':[],'unsupported_claims':[]}
class Tests(unittest.TestCase):
 def test_missing_evidence(self):
  p=pack();p['sources']=p['sources'][:1]
  with self.assertRaises(EvidenceHold):validate_pack(p)
 def test_no_pixel_no_pass(self):
  r=evaluate(Fake(),{'status':'LIVE'},pack(),{'issues':[]})
  self.assertEqual(r['grade'],'TEXT_PASS_IMAGE_PENDING');self.assertFalse(r['verified'])
 def test_invalid_deep(self):
  class Bad(Fake):
   def object(self,p):return {'score':True}
  self.assertEqual(evaluate(Bad(),{'status':'SCHEDULED'},pack(),{'issues':[]})['grade'],'SCHEDULED_HOLD')
 def test_parse_annotations(self):
  g=Gemini('key','test-model',lambda p:{'steps':[{'type':'model_output','content':[{'type':'text','text':'answer','annotations':[{'type':'url_citation','url':'https://example.com'}]}]}]})
  self.assertEqual(len(g.ask('q',True)['citations']),1)
 def test_no_search_no_evidence(self):
  class NoSearch(Fake):
   def ask(self,*args,**kwargs):return {'text':'fact','citations':[]}
  with self.assertRaises(EvidenceHold):Research(NoSearch()).collect('title','topic')
 def test_history_reserved_before_failure(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');g=Generation(s,Fake(),'demo')
   self.assertEqual(g.generate('새로운 전기 주제')['status'],'HOLD')
   with self.assertRaises(EvidenceHold):g.generate('새로운 전기 주제')
   self.assertEqual(s.db.execute('SELECT COUNT(*) FROM generation_jobs').fetchone()[0],1);s.close()
 def test_generation_cap(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');g=Generation(s,Fake(),'demo')
   with self.assertRaises(ValueError):g.generate_many(['a','b','c','d'])
   s.close()
 def test_complete_mock_flow_holds_before_images(self):
  class Full(Fake):
   def ask(self,*args,**kwargs):
    return {'text':'검증 근거','citations':[{'url':s['url']} for s in pack()['sources']]}
   def object(self,prompt):
    if 'R3 SEMANTIC TITLE' in prompt:return {'duplicate':False,'reason':'다른 질문','duplicate_ids':[],'profile':{'core_question':'새 가전의 조건은?','search_intent':'사용 조건 확인','h2':['점검','조건'],'key_facts':['표시 확인'],'practical_outcome':'용도에 맞는 사용'}}
    if 'R3 SEMANTIC BODY' in prompt:return {'duplicate':False,'reason':'독립적인 점검 가치','duplicate_ids':[]}
    if 'duplicate:boolean' in prompt:return {'duplicate':False,'reason':''}
    if '제목 하나' in prompt:return {'title':'새 가전 점검 방법'}
    if '근거 장부를 만드세요' in prompt:return pack()
    if 'claims:[{fact_id' in prompt:
     return {'sources':[{'source_id':'s1','grade':'A','publisher':'제조사'},{'source_id':'s2','grade':'A','publisher':'기관'}],'claims':[{'fact_id':str(i),'source_id':'s1' if i%2 else 's2','quote':'조건을 확인하고 안전한 사용 지침을 따릅니다.','supported':True} for i in range(4)]}
    if '블로그 글을 작성하세요' in prompt:return {'content_html':'<h2>점검</h2><p>'+''.join('점검 조건 '+str(i)+'에서는 표시와 안전한 사용 범위를 제품 설명서와 대조합니다. ' for i in range(90))+'</p><h2>조건</h2><p>표시 확인</p>','search_description':'새 가전 점검 방법과 조건 안내'}
    return super().object(prompt)
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');Sync(s,DemoAdapter(),'demo').run()
   from r3studio.sources import SourceReader
   reader=SourceReader(s,lambda u:{'status':200,'url':u,'headers':{'Content-Type':'text/html'},'body':'<p>'+('조건을 확인하고 안전한 사용 지침을 따릅니다. '*10)+'</p>'})
   result=Generation(s,Full(),'demo',source_reader=reader).generate('새 가전 점검 방법')
   self.assertEqual(result['stage'],'이미지·링크 검사 대기');self.assertEqual(result['status'],'HOLD')
   payload=json.loads(s.db.execute('SELECT payload FROM generation_jobs').fetchone()[0])
   self.assertIn('independent_fact_search',payload);self.assertIn('content',payload);s.close()
 def test_malformed_evidence_holds(self):
  for value in ([],{'sources':[None],'facts':[]},{'sources':[],'facts':[{'text':'x','source_ids':'bad'}]}):
   with self.assertRaises(EvidenceHold):validate_pack(value)
 def test_resume_preserves_job_id(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');g=Generation(s,Fake(),'demo')
   result=g.generate('중단 테스트 주제');again=g.resume(result['job_id'])
   self.assertEqual(again['job_id'],result['job_id'])
   self.assertEqual(s.db.execute('SELECT COUNT(*) FROM generation_jobs').fetchone()[0],1)
   self.assertEqual(s.db.execute('SELECT COUNT(*) FROM generation_history').fetchone()[0],1);s.close()
if __name__=='__main__':unittest.main()

