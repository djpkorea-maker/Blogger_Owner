import json, tempfile, unittest
from copy import deepcopy
from unittest.mock import patch
import test_dev70_replacement as fixture
from test_generation import pack
from r3studio.ai import AIError
from r3studio.evidence import EvidenceHold
from r3studio.generation import Generation
from r3studio.generation_evidence import prepare, writer_context
from r3studio.replacement import Replacement
from r3studio.sources import SourceReader, require_originals, verify_origins
from r3studio.sync import digest
from r3studio.gates import Document
from r3studio.tasks import Cancelled

TITLE='로봇청소기가 문턱에서 걸렸을 때 안전하게 이동하는 방법'
QUOTE='제품 설명서를 확인하고 지정된 안전 점검 조건과 사용 지침을 따릅니다.'
BAD='모든 로봇청소기는 2~10mm 문턱에서 기어와 센서가 손상됩니다.'

def initial():
    p=pack();p.pop('original_verification');p['grounding']={'text':BAD}
    for fact in p['facts']:fact['text']=BAD+' '+fact['id']
    return p

def good_facts():
    p=pack()
    for f in p['facts']:f['text']=QUOTE+' '+f['id']
    return p['facts']

class Reader:
    def __init__(self, count=2):self.calls=0;self.count=count
    def read_many(self,sources,progress):
        self.calls+=1
        return {s['id']:{'status':'FETCHED' if i<self.count else 'UNAVAILABLE',
                 'text':QUOTE,'text_hash':digest(QUOTE),'final_url':s['url']}
                for i,s in enumerate(sources)}

class AI(fixture.AI):
    def __init__(self):super().__init__();self.refills=0;self.verifications=0;self.writers=[];self.mode='ok'
    def object(self,prompt):
        if 'R3 GENERATION ORIGINAL REFILL' in prompt:
            self.refills+=1
            if self.mode=='timeout':raise AIError('응답 시간 초과',diagnostic={'reason':'TIMEOUT'})
            if self.mode=='cancel':raise Cancelled('사용자 중단')
            facts=good_facts()
            if self.mode=='id':facts[0]['source_ids']=['invented-source']
            if self.mode=='few':facts=facts[:3]
            if self.mode=='still_bad':facts[0]['text']=BAD
            return {'facts':facts,'sources':[{'url':'https://invented.example/'}],
                    'original_verification':{'trusted_sources':['invented-source']},'grounding':BAD}
        if 'claims:[{fact_id' in prompt:
            self.verifications+=1;data=json.loads(prompt.split('\n',1)[1])
            return {'sources':[{'source_id':s['id'],'grade':'A','publisher':s['id']} for s in data['sources']],
                    'claims':[{'fact_id':f['id'],'source_id':f['source_ids'][0],
                               'quote':'원문에 존재하지 않는 가짜 인용 구절입니다.' if self.mode=='quote' and self.refills else QUOTE,
                               'supported':BAD not in f['text']} for f in data['facts']]}
        if 'R3 SEMANTIC TITLE' in prompt:
            return {'duplicate':False,'reason':'독립 질문','duplicate_ids':[],
                    'profile':{'core_question':'걸렸을 때 점검','search_intent':'안전 점검',
                               'h2':['설명서 확인','사용 조건'],'key_facts':['설명서 확인'],'practical_outcome':'안전 점검'}}
        if 'R3 SEMANTIC BODY' in prompt:return {'duplicate':False,'reason':'독립 내용','duplicate_ids':[]}
        if 'duplicate:boolean' in prompt:return {'duplicate':False,'reason':'독립 질문'}
        if '근거 장부를 만드세요' in prompt:return initial()
        if '블로그 글을 작성하세요' in prompt:
            self.writers.append(json.loads(prompt.split('\n',1)[1]))
            return {'content_html':fixture.CONTENT.replace('<h2>청소기 점검</h2>','<h2>'+TITLE+'</h2>'),'search_description':'설명서에 따라 문턱에서 멈춘 청소기를 안전하게 점검합니다.'}
        return super().object(prompt)
    def ask(self,*args,**kwargs):
        return {'text':BAD,'citations':[{'url':s['url']} for s in pack()['sources']]}

class Tests(unittest.TestCase):
    def test_unsupported_research_is_rebuilt_once_and_strictly_verified_without_refetch(self):
        ai=AI();reader=Reader();records=[];original=initial()
        p=prepare(ai,original,reader,TITLE,TITLE,record=records.append)
        require_originals(p)
        self.assertEqual(reader.calls,1);self.assertEqual(ai.refills,1);self.assertEqual(ai.verifications,2)
        self.assertEqual(records[-1]['state'],'VERIFIED');self.assertEqual(original,initial())
        self.assertNotIn(BAD,json.dumps(writer_context(TITLE,TITLE,p),ensure_ascii=False))
        self.assertNotIn('grounding',p);self.assertNotIn('invented.example',json.dumps(p))

    def test_still_unsupported_quote_few_facts_or_unknown_source_stops_before_writer(self):
        for mode in ('still_bad','quote','few','id'):
            with self.subTest(mode=mode):
                ai=AI();ai.mode=mode;reader=Reader();records=[]
                with self.assertRaises(EvidenceHold) as caught:prepare(ai,initial(),reader,TITLE,TITLE,record=records.append)
                self.assertEqual(ai.refills,1);self.assertEqual(reader.calls,1);self.assertEqual(ai.writers,[])
                self.assertEqual(records[-1]['state'],'FAILED')
                self.assertEqual(caught.exception.diagnostic['generation_recovery']['limit'],1)
                if hasattr(caught.exception,'recovery_pack'):
                    with self.assertRaises(EvidenceHold):require_originals(caught.exception.recovery_pack)

    def test_one_original_cannot_trigger_expensive_rewrite(self):
        ai=AI()
        with self.assertRaises(EvidenceHold):prepare(ai,initial(),Reader(1),TITLE,TITLE)
        self.assertEqual(ai.refills,0)

    def test_shared_source_root_cannot_be_certified(self):
        p=initial();p['sources'][1]['url']='https://other.manufacturer.example/guide';ai=AI()
        with self.assertRaises(EvidenceHold):prepare(ai,p,Reader(),TITLE,TITLE)
        self.assertEqual(ai.refills,1)

    def test_timeout_and_cancel_keep_original_classification_and_one_attempt(self):
        for mode,kind in [('timeout',AIError),('cancel',Cancelled)]:
            with self.subTest(mode=mode):
                ai=AI();ai.mode=mode;records=[]
                with self.assertRaises(kind) as caught:prepare(ai,initial(),Reader(),TITLE,TITLE,record=records.append)
                self.assertEqual(ai.refills,1);self.assertEqual(records[-1]['state'],'FAILED')
                if mode=='timeout':self.assertEqual(caught.exception.diagnostic['reason'],'TIMEOUT')

    def test_existing_article_verification_remains_strict_and_does_not_rewrite(self):
        ai=AI()
        with self.assertRaises(EvidenceHold) as caught:verify_origins(ai,initial(),Reader())
        self.assertEqual(ai.refills,0)
        with self.assertRaises(EvidenceHold):require_originals(caught.exception.partial_pack)

    def test_writer_filters_noncore_unsupported_fact_and_never_includes_previous_payload(self):
        p=pack();p['grounding']={'text':BAD};p['facts'].append({'id':'bad','text':BAD,'core':False,'kind':'other','source_ids':['s1']})
        p['original_verification']['pack_hash']=digest({'sources':p['sources'],'facts':p['facts']})
        data=writer_context(TITLE,TITLE,p)
        self.assertNotIn(BAD,json.dumps(data,ensure_ascii=False));self.assertEqual(len(data['evidence']['facts']),4)

    def test_full_same_post_replacement_reaches_body_and_two_distinct_images_without_blogger_write(self):
        with tempfile.TemporaryDirectory() as d:
            s,a,pid=fixture.Tests().setup_case(d);ai=AI();fetches=[]
            def fetch(url):
                fetches.append(url)
                return {'status':200,'url':url,'headers':{'content-type':'text/html'},'body':'<p>'+QUOTE*8+'</p>'}
            reader=SourceReader(s,fetch);generator=fixture.Generator()
            with patch('r3studio.sources.SourceReader',return_value=reader):
                svc=Replacement(s,a,ai,d);result=svc.start(pid,TITLE,generator)
            self.assertTrue(result.get('replacement_preview_ready'),result.get('reason'))
            self.assertEqual(result['before']['id'],'1');self.assertEqual(result['proposed_title'],TITLE)
            self.assertEqual(len(Document(result['proposed_content']).images),2)
            self.assertEqual(set(result['image_choices']),{'1','2'});self.assertEqual(len(generator.calls),2)
            self.assertNotEqual(result['image_edit_candidates']['1']['info']['pixel_hash'],result['image_edit_candidates']['2']['info']['pixel_hash'])
            self.assertEqual(len(fetches),2);self.assertEqual(ai.refills,1);self.assertEqual(len(ai.writers),1)
            self.assertNotIn(BAD,json.dumps(ai.writers[0],ensure_ascii=False));self.assertNotIn('replacement_target',ai.writers[0])
            self.assertNotIn('plan',result);self.assertEqual(result['status'],'HOLD')
            self.assertEqual(a.get_post('1')['content'],result['before']['content'])
            job=Generation(s,ai,'blog').load_job(result['replacement_job_id'])
            self.assertEqual(job['payload']['generation_evidence_recovery']['state'],'VERIFIED')
            again=svc.resume(result['proposal_id'],generator)
            self.assertEqual(again['replacement_job_id'],result['replacement_job_id']);self.assertEqual(ai.refills,1)
            s.close()

    def test_failed_recovery_saves_diagnosis_and_never_generates_images(self):
        with tempfile.TemporaryDirectory() as d:
            s,a,pid=fixture.Tests().setup_case(d);ai=AI();ai.mode='still_bad';reader=Reader();generator=fixture.Generator()
            with patch('r3studio.sources.SourceReader',return_value=reader):
                result=Replacement(s,a,ai,d).start(pid,TITLE,generator)
            job=Generation(s,ai,'blog').load_job(result['replacement_job_id'])
            self.assertEqual(job['status'],'HOLD');self.assertEqual(ai.writers,[]);self.assertEqual(generator.calls,[])
            self.assertFalse(result.get('replacement_preview_ready'));self.assertNotIn('original_verification',job['payload']['evidence'])
            self.assertEqual(job['payload']['generation_evidence_recovery']['state'],'FAILED');s.close()

if __name__=='__main__':unittest.main()
