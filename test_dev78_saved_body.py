import io,json,tempfile,unittest
from copy import deepcopy
from unittest.mock import patch
from PIL import Image
import test_dev70_replacement as fixture
from test_dev75_original_refill import AI as BaseAI,TITLE
from test_generation import pack
from r3studio.replacement import Replacement,text_ready
from r3studio.generation import Generation
from r3studio.text_flow import apply_edits,diagnosis,report,POLICY,EDIT_SCHEMA
from r3studio.deep import evaluate
from r3studio.ai import AIError
from r3studio.evidence import EvidenceHold
from r3studio.gates import Document
from r3studio.sync import digest
from r3studio.tasks import Cancelled

OLD='점검 항목 0.'
NEW='제품 설명서에 따른 점검 순서 0.'

class AI(BaseAI):
    def __init__(self,mode='good'):
        super().__init__();self.text_mode=mode;self.repairs=0;self.text_reviews=0;self.audits=0;self.prompts=[]
    def structured_object(self,prompt,schema):
        if 'R3 SAVED BODY PARTIAL REPAIR' in prompt:self.repair_schema=deepcopy(schema)
        return self.object(prompt)
    def ask(self,prompt,*args,**kwargs):
        if '저장된 본문의 핵심 사실' in prompt:self.audits+=1
        return super().ask(prompt,*args,**kwargs)
    def object(self,prompt):
        if 'R3 SAVED BODY PARTIAL REPAIR' in prompt:
            self.repairs+=1;data=json.loads(prompt.rsplit('\n',1)[1]);self.repair_context=data
            if self.text_mode=='timeout':raise AIError('AI 대기 시간 초과',{'reason':'TIMEOUT','summary':'응답 시간 초과','http_status':504})
            if self.text_mode=='cancel':raise Cancelled('사용자 중단')
            if self.text_mode=='no_edits':return {'edits':[]}
            if self.text_mode=='wrong_fragment':return {'edits':[{'old_html':'현재 본문에는 없는 구절','new_html':'검증된 지침','reason':'수정'}]}
            if self.text_mode=='injection':return {'edits':[{'old_html':OLD,'new_html':'<script>alert(1)</script>','reason':'수정'}]}
            return {'edits':[{'old_html':OLD,'new_html':NEW,'reason':'검증된 제품 설명서 조건으로 보완'}]}
        if '글을 근거 장부와 대조하세요' in prompt:
            self.text_reviews+=1;self.prompts.append(prompt);data=json.loads(prompt.rsplit('\n',1)[1])
            review=deepcopy(fixture.REVIEW)
            if self.text_mode=='malformed':return {'fact':'PASS','score':True}
            if self.text_mode!='all_pass' and (OLD in data['post']['content'] or self.text_mode=='still_fail'):
                review.update(fact='UNKNOWN',score=80,severity='minor',issues=['점검 조건의 제품별 근거 확인 필요'],
                    unsupported_claims=[OLD],findings=[{'location':'점검 문단','excerpt':OLD,'reason':'적용 조건 부족','suggestion':'검증된 설명서 조건으로 보완'}])
            return review
        return super().object(prompt)

def seed(directory,ai):
    s,a,pid=fixture.Tests().setup_case(directory);svc=Replacement(s,a,ai,directory)
    with patch.object(Generation,'resume',return_value={'status':'HOLD'}):
        r=svc.start(pid,TITLE,fixture.Generator())
    g=Generation(s,ai,'blog');job=r['replacement_job_id'];fixture.Tests().writer(g,job)
    p=g.load_job(job)['payload'];p['title']=TITLE;p['content']=fixture.CONTENT.replace('<h2>청소기 점검</h2>','<h2>'+TITLE+'</h2>')
    p['deep']['review'].update(fact='UNKNOWN',score=80,severity='minor',issues=['조건 확인 필요'],unsupported_claims=[OLD])
    g.save(job,'이미지·링크 검사 대기','HOLD',p)
    _,proposal=svc.images.load(r['proposal_id']);svc.capture(r['proposal_id'],proposal,g,job)
    return s,a,svc,r,deepcopy(p)

class Tests(unittest.TestCase):
    def test_saved_body_is_repaired_once_then_two_images_without_full_writer_or_post_write(self):
        with tempfile.TemporaryDirectory() as d:
            ai=AI();s,a,svc,r,before=seed(d,ai);gen=fixture.Generator()
            with patch.object(Generation,'resume',side_effect=AssertionError('본문 전체 재생성 금지')):
                out=svc.resume(r['proposal_id'],gen)
            self.assertTrue(out.get('replacement_preview_ready'),out.get('reason'))
            self.assertEqual(out['replacement_job_id'],r['replacement_job_id']);self.assertEqual(ai.repairs,1)
            self.assertEqual(ai.audits,2);self.assertEqual(ai.text_reviews,2);self.assertEqual(ai.writers,[])
            self.assertEqual(len(gen.calls),2);self.assertEqual(len(Document(out['proposed_content']).images),2)
            self.assertEqual(out['text_versions'][0]['content'],before['content']);self.assertIn(NEW,out['proposed_content'])
            self.assertEqual(ai.repair_schema,EDIT_SCHEMA);self.assertEqual(out['text_repair_attempts'][-1]['state'],'VERIFIED')
            self.assertIn('본문 전용 검사',ai.prompts[0]);self.assertNotIn('내부링크 부족 시',ai.prompts[0])
            self.assertEqual(ai.repair_context['title'],TITLE);self.assertNotIn('grounding',ai.repair_context['verified_context'])
            self.assertEqual(a.get_post('1')['content'],out['before']['content']);self.assertNotIn('plan',out)
            self.assertIn('보존 본문 1',report(out));s.close()

    def test_no_changes_wrong_fragment_injection_and_timeout_keep_saved_body_and_block_images(self):
        for mode in ('no_edits','wrong_fragment','injection','timeout'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                ai=AI(mode);s,a,svc,r,before=seed(d,ai);gen=fixture.Generator()
                out=svc.resume(r['proposal_id'],gen);payload=Generation(s,ai,'blog').load_job(r['replacement_job_id'])['payload']
                self.assertEqual(payload['content'],before['content']);self.assertEqual(out['proposed_content'],before['content'])
                self.assertEqual(ai.repairs,1);self.assertEqual(gen.calls,[]);self.assertFalse(out.get('replacement_preview_ready'))
                self.assertIn('text_review',out['error_diagnostic']);self.assertIn('점검 항목 0.',report(out))
                self.assertNotIn('이미지 픽셀 QA·ALT·caption·링크 검증 및 최종 검사 미완료',out['reason'])
                if mode=='timeout':self.assertEqual(out['error_diagnostic']['reason'],'TIMEOUT')
                s.close()

    def test_still_failing_body_does_not_generate_images_or_claim_completion(self):
        with tempfile.TemporaryDirectory() as d:
            ai=AI('still_fail');s,a,svc,r,before=seed(d,ai);gen=fixture.Generator()
            out=svc.resume(r['proposal_id'],gen);self.assertEqual(ai.repairs,1);self.assertEqual(ai.audits,2)
            self.assertEqual(gen.calls,[]);self.assertIn('자동 부분 보완 1회 종료',out['reason'])
            self.assertEqual(out['text_versions'][0]['content'],before['content'])
            self.assertEqual(out['error_diagnostic']['text_review']['states']['fact'],'UNKNOWN');s.close()

    def test_malformed_review_keeps_body_without_rewriting(self):
        with tempfile.TemporaryDirectory() as d:
            ai=AI('malformed');s,a,svc,r,before=seed(d,ai);gen=fixture.Generator()
            out=svc.resume(r['proposal_id'],gen);self.assertEqual(ai.repairs,0);self.assertEqual(gen.calls,[])
            self.assertEqual(out['proposed_content'],before['content']);self.assertIn('응답 형식 오류',out['reason']);s.close()

    def test_cancel_during_partial_repair_persists_body_and_attempt(self):
        with tempfile.TemporaryDirectory() as d:
            ai=AI('cancel');s,a,svc,r,before=seed(d,ai)
            with self.assertRaises(Cancelled):svc.resume(r['proposal_id'],fixture.Generator())
            p=Generation(s,ai,'blog').load_job(r['replacement_job_id'])['payload']
            self.assertEqual(p['content'],before['content']);self.assertEqual(p['text_repair_attempts'][-1]['state'],'FAILED');s.close()

    def test_valid_existing_body_continues_without_repair_or_writer(self):
        with tempfile.TemporaryDirectory() as d:
            ai=AI('all_pass');s,a,svc,r,before=seed(d,ai);gen=fixture.Generator()
            out=svc.resume(r['proposal_id'],gen);self.assertTrue(out.get('replacement_preview_ready'),out.get('reason'))
            self.assertEqual(ai.repairs,0);self.assertEqual(ai.writers,[]);self.assertEqual(len(gen.calls),2)
            self.assertEqual(out['text_versions'][0]['content'],before['content']);s.close()

    def test_text_phase_is_explicit_but_existing_full_review_keeps_link_checks(self):
        ai=AI('all_pass');post={'id':'1','status':'DRAFT','title':TITLE,'content':fixture.CONTENT}
        r=evaluate(ai,post,pack(),{'issues':[]},text_only=True)
        self.assertEqual(r['grade'],'TEXT_PASS_IMAGE_PENDING');self.assertFalse(r['verified'])
        self.assertIn('본문 전용 검사',ai.prompts[-1]);self.assertNotIn('내부링크 부족 시',ai.prompts[-1])
        evaluate(ai,post,pack(),{'issues':[]});self.assertNotIn('본문 전용 검사',ai.prompts[-1]);self.assertIn('내부링크 부족 시',ai.prompts[-1])

    def test_exact_non_overlapping_edits_and_rewrite_limit(self):
        content='<h2>점검</h2><p>'+('보존할 정상 본문. '*100)+'</p><h2>조건</h2><p>대상 문장.</p>'
        with self.assertRaises(EvidenceHold):apply_edits(content,{'edits':[{'old_html':content,'new_html':'완전히 다른 본문','reason':'전체 재작성'}]})
        with self.assertRaises(EvidenceHold):apply_edits(content,{'edits':[{'old_html':'대상 문장.','new_html':'a','reason':'수정'},{'old_html':'<p>대상 문장.</p>','new_html':'b','reason':'수정'}]})
        out=apply_edits(content,{'edits':[{'old_html':'대상 문장.','new_html':'검증된 조건.','reason':'조건 보완'}]})
        self.assertEqual(out,content.replace('대상 문장.','검증된 조건.'))

    def test_image_auth_failure_keeps_first_pass_candidate_and_resume_only_generates_second(self):
        with tempfile.TemporaryDirectory() as d:
            ai=AI('all_pass');s,a,svc,r,before=seed(d,ai)
            class Second:
                model='fake-image'
                def __init__(self):self.calls=[];self.failed=False
                def image(self,prompt):
                    self.calls.append(prompt)
                    if '바닥' in prompt and not self.failed:
                        self.failed=True;raise AIError('이미지 인증 실패',{'reason':'UNAUTHENTICATED','http_status':401,'summary':'이미지 API 인증 실패'})
                    data=io.BytesIO();Image.new('RGB',(1024,576),'blue' if '바닥' in prompt else 'red').save(data,format='PNG');return data.getvalue()
            gen=Second();out=svc.resume(r['proposal_id'],gen)
            self.assertFalse(out.get('replacement_preview_ready'));self.assertEqual(len(gen.calls),2)
            self.assertEqual(out['image_candidates'][0]['result'],'PASS');self.assertEqual(out['error_diagnostic']['reason'],'UNAUTHENTICATED')
            self.assertIn('이미지 2',out['replacement_stage']);first_hash=out['image_candidates'][0]['info']['pixel_hash']
            again=svc.resume(r['proposal_id'],gen);self.assertTrue(again.get('replacement_preview_ready'),again.get('reason'))
            self.assertEqual(len(gen.calls),3);self.assertEqual(again['image_edit_candidates']['1']['info']['pixel_hash'],first_hash)
            self.assertEqual(ai.repairs,0);self.assertEqual(a.get_post('1')['content'],again['before']['content']);s.close()

    def test_factual_unknown_is_never_ignored_as_a_deferred_image_check(self):
        p={'content':fixture.CONTENT,'deep':{'review':deepcopy(fixture.REVIEW)},'fast':{'issues':['이미지 2장 미만','내부링크 확인 필요']}}
        self.assertTrue(text_ready(p));p['deep']['review']['fact']='UNKNOWN'
        self.assertFalse(text_ready(p));d=diagnosis(p)
        self.assertEqual(d['text_review']['states']['fact'],'UNKNOWN');self.assertIn('사실 정확성',d['summary'])

if __name__=='__main__':unittest.main()
