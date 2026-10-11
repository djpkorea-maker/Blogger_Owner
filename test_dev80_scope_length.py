"""Regression: short visible text and model-specific statement after Dev79 repair."""
import json,tempfile,unittest
from copy import deepcopy
from unittest.mock import patch
import test_dev70_replacement as fixture
from test_dev78_saved_body import AI as BaseAI,seed
from test_dev75_original_refill import TITLE
from r3studio.gates import Document,fast_check,text_length,MIN_TEXT_LENGTH,TARGET_TEXT_LENGTH
from r3studio.text_flow import diagnosis,report,repair_contract
from r3studio.generation import Generation
from r3studio.ai import AIError
from r3studio.tasks import Cancelled

UNSCOPED='배터리가 완전히 방전되면 로봇청소기의 상태 표시등이 빨간색으로 켜집니다.'
SCOPED='상태 표시등의 의미는 사용 중인 모델의 설명서에서 확인합니다.'
ANCHOR='<h2>제품 조건 확인</h2>'

def addition(count,offset):
    return ' '.join('문턱에서 안전하게 이동할 때 제품 설명서의 점검 순서 '+str(offset+i)+'번에 해당하는 적용 조건을 확인합니다.' for i in range(count))

def short_body():
    # Visible text is < 1500, HTML including harmless wrappers is > 1800.
    content='<h2>'+TITLE+'</h2><p>'+UNSCOPED+'</p>'+ANCHOR+'<p>'
    for index in range(18):
        content+='<span class="'+('layout '*8)+'">'+addition(1,index)+'</span> '
    return content+'</p>'

class AI(BaseAI):
    def __init__(self,mode='both_second'):
        super().__init__('all_pass');self.mode80=mode;self.contracts=[]
    def object(self,prompt):
        if 'R3 SAVED BODY PARTIAL REPAIR' in prompt:
            self.repairs+=1;data=json.loads(prompt.rsplit('\n',1)[1]);self.contracts.append(data)
            n=self.repairs;mode=self.mode80;edits=[]
            if n==2 and mode=='timeout_second':raise AIError('응답 시간 초과',{'reason':'TIMEOUT','summary':'응답 시간 초과'})
            if n==2 and mode=='cancel_second':raise Cancelled('사용자 중단')
            if n==2 and mode=='invalid_second':return {'edits':[{'old_html':'없는 문장','new_html':SCOPED,'reason':'조건 보완'}]}
            if n==2 and mode=='cycle':
                return {'edits':[{'old_html':SCOPED,'new_html':UNSCOPED,'reason':'잘못된 원복 후보'}]}
            if mode not in ('both_second','still_scope') or n>=2:
                if mode!='still_scope' and UNSCOPED in data['current_html']:
                    edits.append({'old_html':UNSCOPED,'new_html':SCOPED,'reason':'기종 일반화 제거'})
            if mode in ('scope_first','cycle','timeout_second','cancel_second','invalid_second') and n==1:
                return {'edits':edits}
            count=1 if mode=='stays_short' or mode=='both_second' and n==1 else 18
            edits.append({'old_html':ANCHOR,'new_html':ANCHOR+'<p>'+addition(count,100*n)+'</p>',
                          'reason':'검증된 점검 조건을 명료하게 설명하고 부족한 분량 보완'})
            return {'edits':edits}
        if '글을 근거 장부와 대조하세요' in prompt:
            self.text_reviews+=1;self.prompts.append(prompt);data=json.loads(prompt.rsplit('\n',1)[1])
            review=deepcopy(fixture.REVIEW)
            if UNSCOPED in data['post']['content']:
                review.update(fact='FAIL',severity='minor',score=82,
                    issues=['빨간 표시등 설명을 특정 기종으로 한정하거나 제거해야 합니다.'],
                    unsupported_claims=[UNSCOPED],
                    findings=[{'location':'상태 표시 설명 문단','excerpt':UNSCOPED,
                               'reason':'일부 기종 동작을 모든 로봇청소기에 일반화했습니다.',
                               'suggestion':'모델을 확인할 수 없다면 표시등 색 주장을 제거하고 설명서의 해당 표시 의미를 확인하도록 안내하세요.'}])
            return review
        return super().object(prompt)

def seeded(directory,ai):
    s,a,svc,r,before=seed(directory,ai);g=Generation(s,ai,'blog');p=g.load_job(r['replacement_job_id'])['payload']
    p['content']=short_body();p.pop('text_versions',None)
    g.save(r['replacement_job_id'],'Dev79 보완 본문 품질 보류','HOLD',p)
    _,proposal=svc.images.load(r['proposal_id']);svc.capture(r['proposal_id'],proposal,g,r['replacement_job_id'])
    return s,a,svc,r,deepcopy(p)

class Tests(unittest.TestCase):
    def test_dev79_reproduction_two_rounds_fix_remaining_scope_and_length_then_two_images(self):
        with tempfile.TemporaryDirectory() as d:
            ai=AI();s,a,svc,r,before=seeded(d,ai);generator=fixture.Generator()
            self.assertGreater(len(before['content']),1800);self.assertLess(text_length(before['content']),MIN_TEXT_LENGTH)
            with patch.object(Generation,'resume',side_effect=AssertionError('전체 Writer 재실행 금지')):
                out=svc.resume(r['proposal_id'],generator)
            self.assertTrue(out.get('replacement_preview_ready'),out.get('reason'))
            self.assertEqual(ai.repairs,2);self.assertEqual(ai.audits,3);self.assertEqual(ai.text_reviews,3)
            self.assertEqual(out['text_repair_run']['used'],2);self.assertEqual(out['text_repair_run']['state'],'VERIFIED')
            self.assertEqual(out['proposed_title'],TITLE);self.assertEqual(out['replacement_job_id'],r['replacement_job_id'])
            self.assertNotIn(UNSCOPED,out['proposed_content']);self.assertIn(SCOPED,out['proposed_content'])
            self.assertGreaterEqual(out['generation_text_metrics']['text_length'],MIN_TEXT_LENGTH)
            self.assertEqual(len(generator.calls),2);self.assertEqual(len(Document(out['proposed_content']).images),2)
            self.assertEqual(out['text_versions'][0]['content'],before['content']);self.assertEqual(len(out['text_versions']),3)
            first,second=ai.contracts
            self.assertEqual(first['repair_contract']['length']['current'],text_length(before['content']))
            self.assertEqual(second['round'],2);self.assertGreater(second['repair_contract']['length']['current'],first['repair_contract']['length']['current'])
            self.assertGreater(second['repair_contract']['length']['missing_to_minimum'],0)
            self.assertEqual(second['repair_contract']['length']['target_minimum'],TARGET_TEXT_LENGTH)
            self.assertIn('확인된 제품·모델·조건',second['repair_contract']['scope_rule'])
            self.assertIn('부족',report(out));self.assertIn('2/2회',report(out))
            self.assertEqual(ai.writers,[]);self.assertEqual(a.get_post('1')['content'],out['before']['content'])
            self.assertNotIn('plan',out);s.close()

    def test_scope_fix_that_shortens_body_is_followed_by_length_expansion(self):
        with tempfile.TemporaryDirectory() as d:
            ai=AI('scope_first');s,a,svc,r,before=seeded(d,ai);out=svc.resume(r['proposal_id'],fixture.Generator())
            self.assertTrue(out.get('replacement_preview_ready'),out.get('reason'));self.assertEqual(ai.repairs,2)
            self.assertLess(ai.contracts[1]['repair_contract']['length']['current'],text_length(before['content']))
            self.assertEqual(ai.contracts[1]['diagnostic']['text_review']['states']['fact'],'PASS')
            self.assertIn('본문 길이 검토 필요',ai.contracts[1]['repair_contract']['issues']);s.close()

    def test_two_round_budget_does_not_waive_short_body_or_model_specific_fact_failure(self):
        for mode in ('stays_short','still_scope'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                ai=AI(mode);s,a,svc,r,before=seeded(d,ai);generator=fixture.Generator();out=svc.resume(r['proposal_id'],generator)
                self.assertFalse(out.get('replacement_preview_ready'));self.assertEqual(ai.repairs,2);self.assertEqual(generator.calls,[])
                self.assertIn('자동 부분 보완 2회 종료',out['reason']);self.assertEqual(out['text_repair_run']['state'],'HOLD')
                if mode=='stays_short':
                    review=out['error_diagnostic']['text_review'];self.assertGreater(review['text_deficit'],0)
                    self.assertEqual(review['text_length'],text_length(out['proposed_content']))
                    self.assertIn('프로그램 기준 1500자',out['reason'])
                else:
                    self.assertEqual(out['error_diagnostic']['text_review']['states']['fact'],'FAIL')
                    self.assertGreaterEqual(out['generation_text_metrics']['text_length'],MIN_TEXT_LENGTH)
                self.assertEqual(a.get_post('1')['content'],out['before']['content']);s.close()

    def test_second_round_timeout_invalid_fragment_and_cycle_preserve_first_change(self):
        for mode,reason in [('timeout_second','TIMEOUT'),('invalid_second',None),('cycle','TEXT_REPAIR_CYCLE')]:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                ai=AI(mode);s,a,svc,r,before=seeded(d,ai);generator=fixture.Generator();out=svc.resume(r['proposal_id'],generator)
                self.assertEqual(ai.repairs,2);self.assertEqual(generator.calls,[])
                self.assertNotIn(UNSCOPED,out['proposed_content']);self.assertIn(SCOPED,out['proposed_content'])
                self.assertEqual(out['text_versions'][0]['content'],before['content'])
                self.assertEqual(out['text_repair_attempts'][-1]['state'],'FAILED')
                if reason:self.assertEqual(out['error_diagnostic']['reason'],reason)
                self.assertFalse(out.get('replacement_preview_ready'));s.close()

    def test_second_round_cancellation_preserves_original_and_first_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            ai=AI('cancel_second');s,a,svc,r,before=seeded(d,ai)
            with self.assertRaises(Cancelled):svc.resume(r['proposal_id'],fixture.Generator())
            p=Generation(s,ai,'blog').load_job(r['replacement_job_id'])['payload']
            self.assertNotIn(UNSCOPED,p['content']);self.assertIn(SCOPED,p['content'])
            self.assertEqual(p['text_versions'][0]['content'],before['content'])
            self.assertEqual(p['text_repair_run']['state'],'CANCELLED');s.close()

    def test_plain_text_measurement_and_minimum_are_shared_by_fast_and_repair_diagnosis(self):
        content=short_body();result=fast_check({'id':'NEW','title':TITLE,'content':content,'status':'DRAFT'})
        self.assertEqual(result.metrics['text_length'],text_length(content))
        self.assertGreater(len(content),1800);self.assertIn('본문 길이 검토 필요',result.issues)
        p={'title':TITLE,'content':content,'fast':{'issues':result.issues},'deep':{'review':deepcopy(fixture.REVIEW)}}
        d=diagnosis(p);contract=repair_contract(p,d)
        self.assertEqual(d['text_review']['text_deficit'],result.metrics['text_deficit'])
        self.assertEqual(contract['length']['current'],result.metrics['text_length'])
        self.assertIn(str(result.metrics['text_length'])+'자',d['summary'])

    def test_recent_unchanged_review_is_reused_but_changed_model_or_peer_invalidates_it(self):
        for change in ('none','model','peer'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as d:
                ai=AI('stays_short');s,a,svc,r,before=seeded(d,ai);generator=fixture.Generator()
                first=svc.resume(r['proposal_id'],generator);self.assertEqual(ai.audits,3)
                if change=='model':ai.model='changed-model'
                if change=='peer':
                    with s.db:s.db.execute('UPDATE posts SET title=? WHERE post_id=?',('관련 글의 새 제목','2'))
                audits=ai.audits;again=svc.resume(r['proposal_id'],generator)
                self.assertEqual(ai.audits-audits,2 if change=='none' else 3)
                self.assertEqual(again['replacement_job_id'],r['replacement_job_id']);self.assertEqual(generator.calls,[])
                self.assertEqual(a.get_post('1')['content'],again['before']['content']);s.close()

    def test_changed_saved_body_never_uses_previous_body_review(self):
        with tempfile.TemporaryDirectory() as d:
            ai=AI('stays_short');s,a,svc,r,before=seeded(d,ai);svc.resume(r['proposal_id'],fixture.Generator())
            g=Generation(s,ai,'blog');p=g.load_job(r['replacement_job_id'])['payload'];p['content']=p['content'].replace(SCOPED,SCOPED+' 추가 확인.')
            g.save(r['replacement_job_id'],'외부 수정된 보관 본문','HOLD',p)
            old=ai.audits;svc.resume(r['proposal_id'],fixture.Generator());self.assertEqual(ai.audits-old,3);s.close()

    def test_initial_writer_uses_visible_text_target_instead_of_html_character_count(self):
        from test_dev75_original_refill import AI as OriginalAI,QUOTE
        from r3studio.sources import SourceReader
        from r3studio.replacement import Replacement
        class WriterAI(OriginalAI):
            prompt=''
            def object(self,prompt):
                if '블로그 글을 작성하세요' in prompt:self.prompt=prompt
                return super().object(prompt)
        with tempfile.TemporaryDirectory() as d:
            s,a,pid=fixture.Tests().setup_case(d);ai=WriterAI()
            reader=SourceReader(s,lambda url:{'status':200,'url':url,'headers':{'content-type':'text/html'},'body':'<p>'+QUOTE*8+'</p>'})
            with patch('r3studio.sources.SourceReader',return_value=reader):out=Replacement(s,a,ai,d).start(pid,TITLE,fixture.Generator())
            self.assertTrue(out.get('replacement_preview_ready'),out.get('reason'))
            self.assertIn('HTML 태그를 제외하고 공백을 정규화한 실제 본문 1800~2800자',ai.prompt)
            self.assertNotIn('HTML 본문 1800~2800자',ai.prompt)
            self.assertIn('대상을 확인하지 못하면',ai.prompt);s.close()

if __name__=='__main__':unittest.main()
