import json,tempfile,unittest
from copy import deepcopy
from unittest.mock import patch
from r3studio.sync import digest,now
from r3studio.sources import SourceReader,require_originals
from r3studio.evidence import EvidenceHold,validate_pack
from r3studio.generation_evidence import prepare,writer_context
from r3studio.generation_recovery import coverage,backed,supplement,FACT_SCHEMA
from r3studio.generation import Generation
from r3studio.replacement import Replacement
from r3studio.gates import Document
from r3studio.presentation import diagnostic_lines
from r3studio.ai import AIError
from test_generation import pack
from test_dev75_original_refill import AI as BaseAI,TITLE,QUOTE
import test_dev70_replacement as fixture

NEW='추가 제조사 설명서는 해당 모델의 이동 전 안전 점검과 사용 조건을 먼저 확인하도록 안내합니다.'

def one_used():
    p=pack()
    for f in p['facts']:f['source_ids']=['s1','s2']
    for c in p['original_verification']['claims']:c.update(source_id='s1',quote=QUOTE)
    for original in p['original_verification']['originals'].values():
        original.update(text=QUOTE,text_hash=digest(QUOTE))
    p['original_verification']['pack_hash']=digest({'sources':p['sources'],'facts':p['facts']})
    p['retrieved_at']=now()
    return p

class AI(BaseAI):
    def __init__(self):
        super().__init__();self.searches=0;self.additions=0;self.mode='good';self.preserved=[]
    def ask(self,prompt,*args,**kwargs):
        if 'R3 TARGETED EVIDENCE SUPPLEMENT' in prompt:
            self.searches+=1
            if self.mode=='auth':raise AIError('인증 실패',{'reason':'UNAUTHENTICATED','http_status':401})
            if self.mode=='same_search':return {'citations':[{'url':s['url']} for s in pack()['sources']]}
            return {'text':'검색 요약은 원문 사실로 사용하지 않습니다.','citations':[{'url':'https://newmanufacturer.example/manual'}]}
        return super().ask(prompt,*args,**kwargs)
    def object(self,prompt):
        if '근거 장부를 만드세요' in prompt:
            p=one_used();p.pop('original_verification');return p
        if 'R3 GENERATION ORIGINAL REFILL' in prompt:
            self.refills+=1
            p=one_used()
            for f in p['facts']:f['source_ids']=['s1']
            return {'facts':p['facts']}
        if 'R3 SUPPLEMENT ORIGINAL FACTS' in prompt:
            self.additions+=1;data=json.loads(prompt.split('\n',1)[1]);self.preserved=data['preserved_facts']
            sid=next(s['id'] for s in data['sources'] if s.get('assessment')=='PENDING_ORIGINAL_REVIEW')
            return {'facts':[{'id':'fresh','text':NEW,'source_ids':['invented' if self.mode=='bad_id' else sid],'core':False,'kind':'practical'}]}
        if 'claims:[{fact_id' in prompt:
            self.verifications+=1;data=json.loads(prompt.split('\n',1)[1])
            claims=[]
            for f in data['facts']:
                fresh=f['text']==NEW
                claims.append({'fact_id':f['id'],'source_id':f['source_ids'][0] if fresh else 's1',
                               'quote':'원문에 없는 거짓 인용 구절을 제출합니다.' if fresh and self.mode=='bad_quote' else NEW if fresh else QUOTE,
                               'supported':False if fresh and self.mode=='unsupported' else True})
            return {'sources':[{'source_id':sid,'grade':'A','publisher':sid} for sid in data['originals']],'claims':claims}
        return super().object(prompt)

class Reader:
    def __init__(self,mode='good'):self.calls=0;self.mode=mode
    def read_many(self,sources,progress):
        self.calls+=1;result={}
        for s in sources:
            text=NEW if s['id'].startswith('supplement') else QUOTE
            status='UNAVAILABLE' if self.mode=='unavailable' else 'FETCHED'
            if self.mode=='duplicate':text=QUOTE
            result[s['id']]={'status':status,'text':text,'text_hash':digest(text),'final_url':s['url']}
        return result

class Tests(unittest.TestCase):
    def test_actual_quote_links_prevent_unused_source_being_counted(self):
        p=one_used();validate_pack(p);require_originals(p)
        with self.assertRaises(EvidenceHold) as caught:writer_context(TITLE,TITLE,p)
        c=caught.exception.diagnostic['coverage']
        self.assertEqual(c['listed_sources'],2);self.assertEqual(c['used_sources'],1)
        self.assertEqual(c['used_domains'],1);self.assertEqual(c['supported_facts'],4)
        self.assertTrue(all(f['source_ids']==['s1'] for f in backed(p)))
        self.assertIn('지원 연결 1개','\n'.join(diagnostic_lines(caught.exception.diagnostic)))

    def test_one_search_preserves_four_facts_and_reaches_a_writable_verified_pack(self):
        p=one_used();ai=AI();reader=Reader();records=[]
        result=prepare(ai,p,reader,TITLE,TITLE,record=records.append)
        require_originals(result);data=writer_context(TITLE,TITLE,result)
        self.assertEqual(ai.refills,1);self.assertEqual(ai.searches,1);self.assertEqual(ai.additions,1)
        self.assertEqual(reader.calls,1);self.assertEqual(len(ai.preserved),4)
        self.assertEqual(len(data['evidence']['facts']),5)
        self.assertEqual(records[-1]['state'],'VERIFIED');self.assertEqual(records[-1]['coverage_after']['used_domains'],2)
        self.assertEqual([f['text'] for f in result['facts'][:4]],[f['text'] for f in p['facts']])

    def test_no_new_source_unavailable_duplicate_wrong_reference_or_quote_remain_hold(self):
        for mode in ('same_search','unavailable','duplicate','bad_id','bad_quote','unsupported'):
            with self.subTest(mode=mode):
                ai=AI();ai.mode=mode;reader=Reader(mode);records=[]
                with self.assertRaises(EvidenceHold) as caught:prepare(ai,one_used(),reader,TITLE,TITLE,record=records.append)
                self.assertEqual(ai.searches,1);self.assertEqual(ai.refills,1);self.assertEqual(ai.writers,[])
                self.assertEqual(records[-1]['state'],'FAILED');self.assertEqual(caught.exception.diagnostic['supplemental_searches'],1)
                self.assertIn('coverage',caught.exception.diagnostic)
                self.assertNotIn('original_verification',getattr(caught.exception,'partial_pack',{}))
                if mode in ('unavailable','duplicate'):
                    self.assertTrue(caught.exception.diagnostic['supplemental_source_checks'])

    def test_auth_failure_is_not_disguised_as_evidence_failure_or_retried(self):
        ai=AI();ai.mode='auth'
        with self.assertRaises(AIError) as caught:prepare(ai,one_used(),Reader(),TITLE,TITLE)
        self.assertEqual(ai.searches,1);self.assertEqual(ai.additions,0);self.assertEqual(caught.exception.diagnostic['reason'],'UNAUTHENTICATED')

    def test_full_replacement_reads_only_one_extra_original_and_creates_two_images(self):
        with tempfile.TemporaryDirectory() as d:
            s,a,pid=fixture.Tests().setup_case(d);ai=AI();fetches=[]
            def fetch(url):
                fetches.append(url);text=(NEW*8 if 'newmanufacturer' in url else QUOTE*8+url)
                return {'status':200,'url':url,'headers':{'content-type':'text/html'},'body':'<p>'+text+'</p>'}
            reader=SourceReader(s,fetch);generator=fixture.Generator()
            with patch('r3studio.sources.SourceReader',return_value=reader):
                service=Replacement(s,a,ai,d);r=service.start(pid,TITLE,generator)
            self.assertTrue(r.get('replacement_preview_ready'),r.get('reason'))
            self.assertEqual(ai.searches,1);self.assertEqual(ai.refills,1);self.assertEqual(len(fetches),3)
            self.assertEqual(len(generator.calls),2);self.assertEqual(len(ai.writers),1)
            self.assertEqual(len(Document(r['proposed_content']).images),2);self.assertEqual(set(r['image_choices']),{'1','2'})
            self.assertEqual(r['proposed_title'],TITLE);self.assertEqual(r['before']['id'],'1');self.assertNotIn('plan',r)
            self.assertEqual(a.get_post('1')['content'],r['before']['content'])
            self.assertNotEqual(r['image_edit_candidates']['1']['info']['pixel_hash'],r['image_edit_candidates']['2']['info']['pixel_hash'])
            writer=ai.writers[0]['evidence'];used={sid for f in writer['facts'] for sid in f['source_ids']}
            self.assertEqual(used,{'s1','supplement_1'});self.assertNotIn('s2',[src['id'] for src in writer['sources']])
            again=service.resume(r['proposal_id'],generator);self.assertEqual(again['replacement_job_id'],r['replacement_job_id'])
            self.assertEqual(ai.searches,1);self.assertEqual(len(generator.calls),2);s.close()

    def test_old_pending_assessment_does_not_count_as_new_download(self):
        p=one_used();p['sources'][0]['assessment']='PENDING_ORIGINAL_REVIEW'
        p['original_verification']['pack_hash']=digest({'sources':p['sources'],'facts':p['facts']})
        ai=AI();records=[]
        with self.assertRaises(EvidenceHold) as caught:
            supplement(ai,p,Reader('unavailable'),TITLE,TITLE,EvidenceHold('작성 근거 부족'),lambda *a:None,records.append)
        self.assertEqual(ai.searches,1);self.assertEqual(ai.additions,0)
        self.assertIn('접근 불가',str(caught.exception));self.assertEqual(records[-1]['state'],'FAILED')

    def test_supplement_uses_required_facts_schema_if_client_supports_it(self):
        class Strict(AI):
            def structured_object(self,prompt,schema):
                if 'R3 SUPPLEMENT ORIGINAL FACTS' in prompt:self.assert_schema=deepcopy(schema)
                return self.object(prompt)
        ai=Strict()
        out=supplement(ai,one_used(),Reader(),TITLE,TITLE,EvidenceHold('작성 근거 부족'),lambda *a:None,lambda value:None)
        self.assertEqual(ai.assert_schema,FACT_SCHEMA);require_originals(out)

if __name__=='__main__':unittest.main()
