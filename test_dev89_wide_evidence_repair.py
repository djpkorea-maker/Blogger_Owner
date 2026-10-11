"""A broad set of known prose anchors is repaired atomically, never a new article."""
import copy,json,tempfile,unittest
from unittest.mock import patch
from r3studio.final_text_repair import (paragraph_targets,apply_answer,repair_plan,
    repair_batches,batch_schema,repairable_diagnostic,evidence_problem,signature,LEGACY_WIDE_MESSAGE)
from r3studio.article_policy import body_text,MIN_BODY_LENGTH
from r3studio.evidence import EvidenceHold
from r3studio.sync import digest,now
from r3studio.sources import require_originals
from r3studio.gates import Document
from r3studio.text_flow import report
import test_dev84_final_text_repair as base

KEEP='<p>이 구역의 정상 안내는 원문대로 유지합니다. 점검 순서와 대상 제품의 차이는 각 설명서에서 확인합니다.</p>'
def wide_content():
    parts=['<h2>상태와 점검 조건</h2>',KEEP]
    for i,bad in enumerate(base.BAD):
        # Synthetic length buffer solely to exercise the length gate.
        normal=base.GOOD[i]+' '+('예제 문서의 확인된 정상 설명을 보존하는 시험 문장입니다. '*14)
        parts.append('<p>'+bad+' '+normal+'</p>')
        if i==0:parts.append(base.FIG1)
        if i==2:parts.append('<h2>제품별 점검 절차</h2>')
        if i==3:parts.append(base.FIG2)
    parts.extend(['<h2>마지막 확인</h2>',KEEP])
    return ''.join(parts)

class WideAI(base.AI):
    def __init__(self,mode='good',observe=lambda:None):
        super().__init__(mode);self.observe=observe
    def structured_object(self,prompt,schema):
        if not prompt.startswith('R3 FINAL EVIDENCE PARAGRAPH REPAIR:'):
            return super().structured_object(prompt,schema)
        self.repairs+=1;self.requests.append(prompt);self.observe()
        data=json.loads(prompt.split('\n',1)[1])
        assert schema==batch_schema(data['blocks'])
        edits=[]
        for b in data['blocks']:
            new=b['old_html']
            for bad in base.BAD:new=new.replace(bad,'')
            if self.mode=='short':new='<p>'+base.GOOD[0]+'</p>'
            if self.mode=='unchanged':new=b['old_html']
            edits.append({'block_id':b['block_id'],'new_html':new,'reason':'원문으로 확인되지 않은 확장만 제거하고 정상 설명 유지'})
        if self.repairs==2 and self.mode=='second_fail':edits[0]['block_id']='p1'
        if self.repairs==2 and self.mode=='cancel':
            from r3studio.tasks import Cancelled
            raise Cancelled('두 번째 묶음에서 중단')
        return {'edits':edits}

class Tests(unittest.TestCase):
    def fixture(self,d,mode='good',legacy=False):
        s,server,service,pid,_,_=base.Tests().fixture(d)
        _,p=service.load(pid);p['proposed_content']=wide_content()
        for key,c in p['image_choices'].items():
            c['candidate']['target']={'slot':int(key),'url':c['expected_url'],'article_hash':digest(p['proposed_content'])}
        p['error_diagnostic']=base.diagnostic();p['final_evidence_for']=signature(p)
        service.save(pid,p)
        # Exercise real Bridge image uploads before the factual HOLD. Later
        # repair and final validation must reuse both saved DONE receipts.
        error=EvidenceHold('원문 근거 확인 필요',diagnostic=base.diagnostic(),partial_pack=p['final_evidence_pack'])
        with patch('r3studio.repair_images.collect_cached',side_effect=error):
            held=service.validate(pid)
        self.assertEqual(held['status'],'HOLD');self.assertEqual(len(server.uploads),2)
        _,p=service.load(pid)
        if legacy:
            p['final_text_repairs']=[{'state':'HOLD','reason':LEGACY_WIDE_MESSAGE,'at':now(),
                'before_hash':signature(p),'before_content':p['proposed_content']}]
            p['error_diagnostic']={'reason':'FINAL_EVIDENCE_REPAIR_HOLD','summary':LEGACY_WIDE_MESSAGE,
                                   'original_evidence_diagnostic':base.diagnostic()}
            service.save(pid,p)
        before=copy.deepcopy(p)
        def observe():
            current=service.load(pid)[1]
            self.assertEqual(current['proposed_content'],before['proposed_content'])
            self.assertEqual(current['image_choices'],before['image_choices'])
            self.assertNotIn('plan',current)
        ai=WideAI(mode,observe);service.ai=ai
        return s,server,service,pid,ai,before

    def test_reported_half_guard_reproduced_with_five_actual_anchors(self):
        c=wide_content();blocks=paragraph_targets(c,base.diagnostic());scope=repair_plan(c,blocks)
        self.assertGreater(scope['target_percent'],50);self.assertEqual(len(blocks),5)
        self.assertEqual(scope['mode'],'BROAD_ANCHORED_PARAGRAPHS')
        self.assertEqual([len(g) for g in repair_batches(blocks,scope)],[4,1])
        self.assertEqual(scope['body_hash'],digest(c))
        answer={'edits':[{'block_id':b['block_id'],'new_html':b['old_html'].replace(base.BAD[i],''),'reason':'예제 보완'} for i,b in enumerate(blocks)]}
        result,changes=apply_answer(c,blocks,answer)
        self.assertEqual(Document(result).images,Document(c).images)
        self.assertEqual(Document(result).headings,Document(c).headings)
        self.assertEqual(result.count(KEEP),2)
        self.assertIn(base.FIG1,result);self.assertIn(base.FIG2,result)
        self.assertGreaterEqual(len(body_text(result)),MIN_BODY_LENGTH)
        self.assertEqual(len(changes),5)

    def test_changed_offsets_html_claims_and_nonprose_anchors_are_rejected(self):
        c=wide_content();b=paragraph_targets(c,base.diagnostic())
        for field,value in (('start',0),('end',len(c)),('old_html',KEEP),('text','다른 문장')):
            bad=copy.deepcopy(b);bad[0][field]=value
            with self.subTest(field=field),self.assertRaises(EvidenceHold):repair_plan(c,bad)
        with self.assertRaises(EvidenceHold):repair_plan(c,b+b[:1])
        bad=copy.deepcopy(b);bad[0]['claims']=[{'text':'현재 본문에는 전혀 없는 진단입니다.'}]
        with self.assertRaises(EvidenceHold):repair_plan(c,bad)
        with self.assertRaises(EvidenceHold):paragraph_targets(c,{'unverified_claims':[{'text':Document(base.FIG1).text[-1]}]})

    def test_normal_partial_repair_keeps_one_request_and_batch_schema_has_exact_ids(self):
        c=base.content();b=paragraph_targets(c,base.diagnostic());scope=repair_plan(c,b)
        self.assertEqual(scope['mode'],'ANCHORED_PARAGRAPHS')
        self.assertEqual(len(repair_batches(b,scope)),1)
        self.assertEqual(batch_schema(b)['properties']['edits']['items']['properties']['block_id']['enum'],[x['block_id'] for x in b])
        b.append(copy.deepcopy(b[0]))
        with self.assertRaises(EvidenceHold):repair_plan(c,b)

    def test_old_scope_hold_only_unwraps_exact_diagnostic(self):
        original=base.diagnostic()
        d={'reason':'FINAL_EVIDENCE_REPAIR_HOLD','summary':LEGACY_WIDE_MESSAGE,'original_evidence_diagnostic':original}
        self.assertTrue(repairable_diagnostic(d));self.assertEqual(evidence_problem(d),original)
        for change in ({'summary':'시간 초과'},{'reason':'TIMEOUT'},
                       {'original_evidence_diagnostic':{'reason':'ORIGINAL_REVIEW_FORMAT'}}):
            self.assertFalse(repairable_diagnostic(dict(d,**change)))

    def test_wide_repair_passes_full_pipeline_and_preserves_uploaded_pixels_and_schedule(self):
        with tempfile.TemporaryDirectory() as d:
            s,server,service,pid,ai,before=self.fixture(d)
            with base.Tests().checks(service):result=service.repair_evidence(pid)
            self.assertEqual(result['status'],'PASS',result.get('reason'));require_originals(result['evidence'])
            self.assertEqual(ai.repairs,2);self.assertEqual(ai.images,2)
            self.assertEqual(result['before'],before['before'])
            self.assertEqual(result['proposed_title'],before['proposed_title'])
            self.assertEqual(len(server.uploads),2)
            for key in ('1','2'):
                old=before['image_choices'][key];new=result['image_choices'][key]
                for field in ('request_id','receipt','expected_url','upload_context'):self.assertEqual(new[field],old[field])
                for field in ('info','file','alt','caption'):self.assertEqual(new['candidate'][field],old['candidate'][field])
            self.assertEqual(result['final_text_versions'][-1]['content'],before['proposed_content'])
            text=report(result);self.assertIn('보완 범위: 지적 문단 5개',text);self.assertIn('2/2 묶음',text)
            self.assertFalse(any(bad in result['proposed_content'] for bad in base.BAD))
            with base.Tests().checks(service):again=service.validate(pid)
            self.assertEqual(again['status'],'PASS');self.assertEqual(len(server.uploads),2)
            s.close()

    def test_second_batch_failure_and_cancellation_are_atomic(self):
        from r3studio.tasks import Cancelled
        for mode in ('second_fail','cancel'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                s,server,service,pid,ai,before=self.fixture(d,mode)
                with base.Tests().checks(service):
                    if mode=='cancel':
                        with self.assertRaises(Cancelled):service.repair_evidence(pid)
                        result=service.load(pid)[1]
                    else:result=service.repair_evidence(pid)
                self.assertEqual(ai.repairs,2)
                self.assertEqual(result['proposed_content'],before['proposed_content'])
                self.assertEqual(result['image_choices'],before['image_choices'])
                self.assertEqual(len(server.uploads),2);self.assertNotIn('plan',result)
                run=result['final_text_repairs'][-1]
                self.assertEqual(run['batches'][0]['state'],'CANDIDATE_CHECKED')
                self.assertEqual(run['batches'][1]['state'],'CANCELLED' if mode=='cancel' else 'HOLD')
                self.assertIn('미반영 후보 보완 전:',report(result));s.close()

    def test_short_unverified_pixels_and_unchanged_candidates_do_not_replace_body(self):
        for mode in ('short','unsupported','pixel_fail','unchanged'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                s,server,service,pid,ai,before=self.fixture(d,mode)
                with base.Tests().checks(service):result=service.repair_evidence(pid)
                self.assertEqual(result['status'],'HOLD',mode)
                self.assertEqual(result['proposed_content'],before['proposed_content'])
                self.assertEqual(result['image_choices'],before['image_choices'])
                self.assertEqual(len(server.uploads),2);self.assertNotIn('plan',result);s.close()

    def test_current_saved_half_guard_resumes_without_new_generation(self):
        from r3studio.replacement import Replacement
        with tempfile.TemporaryDirectory() as d:
            s,server,service,pid,ai,before=self.fixture(d,legacy=True)
            replacement=Replacement(s,service.adapter,ai,d)
            # Resume must reach the repair route, not Generation/image APIs.
            with patch.object(replacement.images,'repair_evidence',return_value={'route':'repair'}) as route:
                self.assertEqual(replacement.resume(pid,None),{'route':'repair'})
            route.assert_called_once_with(pid)
            with base.Tests().checks(service):result=service.repair_evidence(pid)
            self.assertEqual(result['status'],'PASS',result.get('reason'))
            self.assertEqual(ai.repairs,2);self.assertEqual(len(server.uploads),2);s.close()

    def test_changed_body_cannot_resume_an_old_half_guard(self):
        with tempfile.TemporaryDirectory() as d:
            s,server,service,pid,ai,before=self.fixture(d,legacy=True)
            _,p=service.load(pid);p['proposed_content']+='<p>사용자가 변경한 본문입니다.</p>';service.save(pid,p)
            with self.assertRaisesRegex(EvidenceHold,'현재 본문이 다릅니다'):service.repair_evidence(pid)
            self.assertEqual(ai.repairs,0);self.assertEqual(service.load(pid)[1]['proposed_content'],p['proposed_content']);s.close()

    def test_final_quality_hold_after_candidate_has_no_apply_plan(self):
        with tempfile.TemporaryDirectory() as d:
            s,server,service,pid,ai,before=self.fixture(d)
            with base.Tests().checks(service,'deep_fail'):result=service.repair_evidence(pid)
            self.assertEqual(result['status'],'HOLD');self.assertNotIn('plan',result)
            self.assertEqual(result['final_text_repairs'][-1]['state'],'APPLIED_HOLD')
            self.assertEqual(result['final_text_versions'][-1]['content'],before['proposed_content'])
            self.assertEqual(len(server.uploads),2);s.close()

if __name__=='__main__':unittest.main()
