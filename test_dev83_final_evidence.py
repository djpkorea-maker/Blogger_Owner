"""Regression: show real final evidence failures without losing body/images."""
import copy
import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from r3studio.ai import AIError
from r3studio.evidence import EvidenceHold,collect_cached
from r3studio.sources import verify_origins,require_originals
from r3studio.sync import Store,digest
from r3studio.text_flow import report
from r3studio.presentation import history_text
from r3studio.tasks import TaskLog,finish_validation
import test_dev82_upload_resume as uploads

QUOTES=[
    '장애물에 걸렸을 때에는 제품을 정지하고 상태를 확인합니다.',
    '이 모델의 점검 순서는 해당 제품의 사용 설명서에 나와 있습니다.',
    '전원을 끈 뒤 사용 설명서에서 허용하는 범위를 점검합니다.',
    '이 안내는 해당 모델의 명시된 사용 조건에서만 적용됩니다.'
]

def ledger():
    sources=[{'id':'s1','url':'https://maker.example/manual','grade':'A'},
             {'id':'s2','url':'https://agency.example/guide','grade':'A'}]
    facts=[{'id':'f'+str(i+1),'text':text,'source_ids':['s1' if i%2==0 else 's2'],
            'core':i<2,'kind':['core','core','practical','condition'][i]}
           for i,text in enumerate(QUOTES)]
    return {'sources':sources,'facts':facts}

def originals():
    text=' '.join(QUOTES)*4
    return {sid:{'status':'FETCHED','text':text,'text_hash':digest(text),
        'final_url':url,'checked_at':'2026-10-11T00:00:00+00:00'}
        for sid,url in [('s1','https://maker.example/manual'),('s2','https://agency.example/guide')]}

class Reader:
    def __init__(self):self.reads=0
    def read_many(self,sources,progress):
        self.reads+=1
        progress('근거 원문 확인',len(sources),len(sources))
        return copy.deepcopy(originals())

class AI:
    model='fixture'
    def __init__(self,states):
        self.states=list(states);self.requests=[]
    def structured_object(self,prompt,schema):
        self.requests.append(prompt)
        state=self.states.pop(0)
        if isinstance(state,Exception):raise state
        claims=[{'fact_id':f'f{i+1}','source_id':'s1' if i%2==0 else 's2',
                 'quote':q,'supported':True} for i,q in enumerate(QUOTES)]
        if state=='format':return {'sources':[], 'claims':'invalid'}
        if state=='short':
            claims[3]['quote']='이 문장은 실제 원문 안에 존재하지 않는 임의의 인용입니다.'
        if state=='unlinked':claims[3]['source_id']='s1'
        return {'sources':[{'source_id':'s1','grade':'A','publisher':'제조사'},
                           {'source_id':'s2','grade':'A','publisher':'독립 기관'}],
                'claims':claims}

class Tests(unittest.TestCase):
    def collect(self,store,ai,reader,record=lambda value:None,recheck=True):
        with patch('r3studio.evidence.Research.collect',return_value=ledger()),patch('r3studio.sources.SourceReader',return_value=reader):
            return collect_cached(store,ai,'점검','점검','fixture',article='<p>보존할 본문</p>',
                recheck_originals=recheck,record_review=record)
    def test_three_supported_facts_show_exact_claim_counts_and_sources(self):
        with self.assertRaises(EvidenceHold) as caught:verify_origins(AI(['short']),ledger(),Reader())
        detail=caught.exception.diagnostic
        self.assertEqual(detail['summary'],'원문에서 확인된 사실 4개 미만')
        self.assertEqual(detail['verification_counts']['supported_facts'],3)
        self.assertEqual(detail['verification_counts']['listed_facts'],4)
        self.assertEqual(detail['unverified_claims'],[{'text':QUOTES[3],'reason':'제시된 인용 구절이 실제 추출 원문과 일치하지 않음'}])
        proposal={'replacement_job_id':3,'replacement_stage':'이미지 자동 생성',
                  'validation_stage':'수정된 본문 근거 최종 재검증','error_diagnostic':detail}
        text=report(proposal)
        self.assertIn('현재 단계: 수정된 본문 근거 최종 재검증',text)
        self.assertIn('지원 확인 3개',text)
        self.assertIn(QUOTES[3],text)
        self.assertIn('실제 추출 원문과 일치하지 않음',text)
        self.assertIn('https://maker.example/manual / FETCHED',text)
    def test_mismatched_claim_source_is_recorded_instead_of_silently_skipped(self):
        with self.assertRaises(EvidenceHold) as caught:verify_origins(AI(['unlinked']),ledger(),Reader())
        self.assertIn('출처 ID',caught.exception.diagnostic['unverified_claims'][0]['reason'])
    def test_same_originals_recheck_can_recover_and_cache_only_verified_pack(self):
        s=Store(':memory:');reader=Reader();ai=AI(['short','pass']);events=[]
        value=self.collect(s,ai,reader,events.append)
        require_originals(value)
        self.assertEqual(reader.reads,1);self.assertEqual(len(ai.requests),2)
        self.assertIn('previous_review_diagnostic',ai.requests[1])
        self.assertEqual([v['state'] for v in events],['HOLD','STARTED','VERIFIED'])
        self.assertEqual(value['facts'],ledger()['facts'])
        self.assertEqual(s.db.execute('SELECT COUNT(*) FROM evidence_packs').fetchone()[0],1)
        s.close()
    def test_two_failures_stop_and_do_not_cache_partial_as_verified(self):
        s=Store(':memory:');reader=Reader();ai=AI(['short','short']);events=[]
        with self.assertRaises(EvidenceHold) as caught:self.collect(s,ai,reader,events.append)
        detail=caught.exception.diagnostic
        self.assertEqual(detail['verification_counts']['supported_facts'],3)
        self.assertEqual(detail['original_recheck']['used'],1)
        self.assertEqual(len(ai.requests),2);self.assertEqual(reader.reads,1)
        self.assertEqual(s.db.execute('SELECT COUNT(*) FROM evidence_packs').fetchone()[0],0)
        self.assertIn(QUOTES[3],report({'error_diagnostic':detail}))
        s.close()
    def test_transport_error_during_retry_keeps_classification_and_prior_claims(self):
        s=Store(':memory:');error=AIError('대기 시간 초과',{'reason':'TIMEOUT','summary':'응답 시간 초과'})
        ai=AI(['short',error])
        with self.assertRaises(AIError) as caught:self.collect(s,ai,Reader())
        self.assertEqual(caught.exception.diagnostic['reason'],'TIMEOUT')
        self.assertEqual(caught.exception.diagnostic['unverified_claims'][0]['text'],QUOTES[3])
        self.assertEqual(len(ai.requests),2);s.close()
    def test_other_flows_do_not_gain_unrequested_extra_ai_call(self):
        s=Store(':memory:');ai=AI(['short'])
        with self.assertRaises(EvidenceHold):self.collect(s,ai,Reader(),recheck=False)
        self.assertEqual(len(ai.requests),1);s.close()
    def test_format_failure_does_not_enter_truth_recheck(self):
        s=Store(':memory:');ai=AI(['format','format']);events=[]
        with self.assertRaises(EvidenceHold) as caught:self.collect(s,ai,Reader(),events.append)
        self.assertEqual(caught.exception.diagnostic['reason'],'ORIGINAL_REVIEW_FORMAT')
        self.assertEqual(len(ai.requests),2);self.assertEqual(events,[])
        self.assertNotIn('original_recheck',caught.exception.diagnostic)
        s.close()
    def test_cancelled_original_recheck_propagates_without_false_pass(self):
        from r3studio.tasks import Cancelled
        s=Store(':memory:');ai=AI(['short',Cancelled('사용자 중단')])
        with self.assertRaises(Cancelled):self.collect(s,ai,Reader())
        self.assertEqual(s.db.execute('SELECT COUNT(*) FROM evidence_packs').fetchone()[0],0)
        s.close()
    def test_old_summary_only_record_explicitly_reports_missing_details(self):
        text=report({'error_diagnostic':{'reason':'EVIDENCE_ORIGINALS_INCOMPLETE','summary':'원문에서 확인된 사실 4개 미만'}})
        self.assertIn('이전 기록에 문장별 미검증 항목이 없습니다',text)
    def test_final_hold_persists_assets_receipts_and_displays_details_after_reload(self):
        fixture=uploads.Tests()
        with tempfile.TemporaryDirectory() as directory:
            s,server,adapter,service,pid=fixture.fixture(directory)
            before=copy.deepcopy(service.load(pid)[1]);reader=Reader()
            service.ai=AI(['short','short'])
            with fixture.final_checks(),patch('r3studio.repair_images.collect_cached',side_effect=collect_cached),patch('r3studio.evidence.Research.collect',return_value=ledger()),patch('r3studio.sources.SourceReader',return_value=reader):
                result=service.validate(pid)
            self.assertEqual(result['status'],'HOLD')
            saved=service.load(pid)[1]
            self.assertEqual(saved['proposed_content'],before['proposed_content'])
            self.assertEqual(saved['before'],before['before'])
            for slot in ('1','2'):
                self.assertEqual(saved['image_choices'][slot]['candidate'],before['image_choices'][slot]['candidate'])
                self.assertEqual(saved['image_choices'][slot]['request_id'],before['image_choices'][slot]['request_id'])
                self.assertTrue(saved['image_choices'][slot]['receipt']['ok'])
            self.assertEqual(server.uploads,[uploads.RID,uploads.RID2])
            self.assertEqual(len(saved['final_evidence_attempts']),3)
            self.assertIn(QUOTES[3],report(saved))
            task=TaskLog(s,'최종 검증')
            finish_validation(task,result)
            history=history_text(s.db.execute('SELECT * FROM task_runs').fetchall())
            self.assertIn(QUOTES[3],history);self.assertIn('보류',history)
            service.ai=AI(['pass'])
            with fixture.final_checks(),patch('r3studio.repair_images.collect_cached',side_effect=collect_cached),patch('r3studio.evidence.Research.collect',return_value=ledger()),patch('r3studio.sources.SourceReader',return_value=Reader()):
                recovered=service.validate(pid)
            self.assertEqual(recovered['status'],'PASS')
            self.assertEqual(server.uploads,[uploads.RID,uploads.RID2])
            self.assertNotIn('error_diagnostic',recovered)
            self.assertEqual(recovered['proposed_content'],before['proposed_content'])
            s.close()

if __name__=='__main__':unittest.main()
