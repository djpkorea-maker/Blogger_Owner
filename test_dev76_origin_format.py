import json,tempfile,unittest
from copy import deepcopy
from unittest.mock import patch
from r3studio.ai import Gemini,AIError
from r3studio.origin_response import SCHEMA,shape_issues,request_review
from r3studio.sources import verify_origins,require_originals,SourceReader
from r3studio.generation_evidence import prepare
from r3studio.generation import Generation
from r3studio.evidence import EvidenceHold
from r3studio.presentation import diagnostic_lines
from r3studio.replacement import Replacement
from r3studio.gates import Document
from r3studio.tasks import Cancelled
from test_dev75_original_refill import AI,Reader,initial,good_facts,TITLE,QUOTE,BAD
import test_dev70_replacement as fixture

def context():
    p=initial();p['facts']=good_facts()
    return {'facts':p['facts'],'sources':p['sources'],'originals':Reader().read_many(p['sources'],lambda *a:None)}

def valid():
    c=context()
    return {'sources':[{'source_id':s['id'],'grade':'A','publisher':s['id']} for s in c['sources']],
            'claims':[{'fact_id':f['id'],'source_id':f['source_ids'][0],'quote':QUOTE,'supported':True} for f in c['facts']]}

def response(value):return {'outputs':[{'type':'text','text':value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)}]}

class Tests(unittest.TestCase):
    def test_real_client_sends_required_schema_and_repairs_missing_sources_once(self):
        calls=[]
        def transport(payload):
            calls.append(payload);return response({'claims':{}} if len(calls)==1 else valid())
        review,trace=request_review(Gemini('test','mock',transport),context())
        self.assertEqual(review,valid());self.assertEqual(len(calls),2)
        for p in calls:
            self.assertEqual(p['response_format']['schema'],SCHEMA)
            self.assertFalse(p['store']);self.assertNotIn('tools',p)
        self.assertIn('sources: 필수 목록 누락',calls[1]['input'])
        self.assertEqual([t['state'] for t in trace],['FORMAT_ERROR','VALID_SHAPE'])

    def test_invalid_json_and_array_root_have_one_bounded_repair(self):
        for raw in ('{"secret":"PRIVATE","claims":','[]'):
            with self.subTest(raw=raw):
                calls=[]
                def transport(p):calls.append(p);return response(raw if len(calls)==1 else valid())
                out,trace=request_review(Gemini('test','mock',transport),context())
                self.assertEqual(out,valid());self.assertEqual(len(calls),2)
                self.assertNotIn('PRIVATE',json.dumps(trace));self.assertNotIn('PRIVATE',calls[1]['input'])

    def test_exhaustion_records_missing_and_wrong_types_without_raw_output(self):
        calls=[]
        def transport(p):calls.append(p);return response({'claims':{},'secret':'PRIVATE'})
        ai=Gemini('test','mock',transport);reader=Reader();p=initial();p['facts']=good_facts()
        with self.assertRaises(EvidenceHold) as caught:verify_origins(ai,p,reader)
        d=caught.exception.diagnostic
        self.assertEqual(len(calls),2);self.assertEqual(reader.calls,1)
        self.assertEqual(d['reason'],'ORIGINAL_REVIEW_FORMAT');self.assertEqual(len(d['response_format_attempts']),2)
        rendered='\n'.join(diagnostic_lines(d));self.assertIn('claims: array 필요 / 실제 dict',rendered);self.assertIn('sources: 필수 목록 누락',rendered)
        self.assertNotIn('PRIVATE',rendered);self.assertNotIn('PRIVATE',json.dumps(d))
        with self.assertRaises(EvidenceHold):require_originals(caught.exception.partial_pack)

    def test_format_failure_does_not_rewrite_fact_ledger_or_start_writer(self):
        class Bad(AI):
            def object(self,p):
                if 'claims:[{fact_id' in p:self.verifications+=1;return {'claims':{}}
                return super().object(p)
        ai=Bad()
        with self.assertRaises(EvidenceHold) as caught:prepare(ai,initial(),Reader(),TITLE,TITLE)
        self.assertEqual(ai.verifications,2);self.assertEqual(ai.refills,0);self.assertEqual(ai.writers,[])
        self.assertEqual(caught.exception.diagnostic['reason'],'ORIGINAL_REVIEW_FORMAT')

    def test_types_ids_and_duplicate_rows_are_not_silently_coerced(self):
        values=[]
        v=valid();v['claims'][0]['supported']='true';values.append(v)
        v=valid();v['claims'][0]['fact_id']=0;values.append(v)
        v=valid();v['claims'][0]['source_id']='invented';values.append(v)
        v=valid();v['sources'][0]['grade']='PASS';values.append(v)
        v=valid();v['claims'].append(dict(v['claims'][0],supported=False));values.append(v)
        for v in values:
            with self.subTest(value=v):self.assertTrue(shape_issues(v,context()))

    def test_good_shape_does_not_certify_wrong_quotes_or_unsupported_claims(self):
        for field,value in [('quote','원문에 없는 인용 문장을 만들어 반환합니다.'),('supported',False)]:
            with self.subTest(field=field):
                v=valid();v['claims'][0][field]=value;calls=[]
                def transport(p):calls.append(p);return response(v)
                p=initial();p['facts']=good_facts()
                with self.assertRaises(EvidenceHold) as caught:verify_origins(Gemini('test','mock',transport),p,Reader())
                self.assertEqual(len(calls),1);self.assertEqual(caught.exception.diagnostic['reason'],'EVIDENCE_ORIGINALS_INCOMPLETE')
                with self.assertRaises(EvidenceHold):require_originals(caught.exception.partial_pack)

    def test_auth_timeout_and_cancel_are_not_retried_as_format_errors(self):
        for error in [AIError('인증 실패',{'http_status':401,'reason':'UNAUTHENTICATED'}),AIError('응답 시간 초과',{'reason':'TIMEOUT'}),Cancelled('사용자 중단')]:
            with self.subTest(error=error):
                calls=[]
                class Failing:
                    def object(self,p):calls.append(p);raise error
                with self.assertRaises(type(error)):request_review(Failing(),context())
                self.assertEqual(len(calls),1)

    def test_reported_post_refill_shape_failure_is_repaired_then_body_and_images_are_ready(self):
        with tempfile.TemporaryDirectory() as d:
            s,a,pid=fixture.Tests().setup_case(d);fetches=[]
            def fetch(url):fetches.append(url);return {'status':200,'url':url,'headers':{'content-type':'text/html'},'body':'<p>'+QUOTE*8+'</p>'}
            reader=SourceReader(s,fetch)
            class ActualContractAI(AI):
                def __init__(self):
                    super().__init__();self.payloads=[];self.broken=False;self.client=Gemini('test','mock',self.transport)
                def transport(self,p):
                    self.payloads.append(p)
                    if self.refills and not self.broken:
                        self.broken=True;return response({'sources':None,'claims':[]})
                    return response(super().object(p['input'].rsplit('\n지정한 스키마의 JSON 객체',1)[0]))
                def structured_object(self,p,schema):return self.client.structured_object(p,schema)
            ai=ActualContractAI();generator=fixture.Generator()
            with patch('r3studio.sources.SourceReader',return_value=reader):result=Replacement(s,a,ai,d).start(pid,TITLE,generator)
            self.assertTrue(result.get('replacement_preview_ready'),result.get('reason'))
            self.assertEqual(len(ai.payloads),3);self.assertTrue(ai.broken);self.assertEqual(ai.refills,1)
            self.assertEqual(len(fetches),2);self.assertEqual(len(ai.writers),1);self.assertEqual(len(generator.calls),2)
            self.assertEqual(len(Document(result['proposed_content']).images),2);self.assertEqual(result['before']['id'],'1')
            self.assertEqual(result['proposed_title'],TITLE);self.assertEqual(result['status'],'HOLD');self.assertNotIn('plan',result)
            self.assertNotIn(BAD,json.dumps(ai.writers,ensure_ascii=False))
            job=Generation(s,ai,'blog').load_job(result['replacement_job_id'])
            self.assertEqual(job['payload']['evidence']['original_verification']['response_format_attempts'][-1]['state'],'VALID_SHAPE')
            self.assertEqual(a.get_post('1')['content'],result['before']['content']);s.close()

if __name__=='__main__':unittest.main()
