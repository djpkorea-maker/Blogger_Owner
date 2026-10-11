"""Final factual HOLD -> anchored local prose repair -> strict recheck, no image regeneration."""
import copy,json,tempfile,unittest
from contextlib import ExitStack
from unittest.mock import patch
from r3studio.final_text_repair import paragraph_targets,apply_answer,original_context,signature
from r3studio.evidence import EvidenceHold,ArticleContext,collect_cached,display_url
from r3studio.sources import verify_origins,require_originals
from r3studio.sync import now,digest,Store
from r3studio.text_flow import report
from r3studio.gates import Result,Document
from r3studio.readiness import require_settings,AI_ACTIONS
import test_dev82_upload_resume as uploads

BAD=[
    '또한 장애물이나 문턱 걸림으로 인해 멈췄을 때 에러 알림이 나타난 후, 모델에 따라 약 10분 이내에 전원이 자동으로 꺼질 수 있습니다.',
    '문턱이나 턱에 걸려 멈춘 상태에서 로봇청소기를 억지로 밀거나 강하게 잡아당기면 내부 자이로 및 맵 위치 인식이 완전히 어긋나거나 바닥과 맞닿은 하부 마감재가 심하게 긁힐 위험이 발생합니다.',
    '따라서 이동이 필요할 때는 조작부나 앱을 통해 반드시 일시 정지를 먼저 진행한 뒤, 양손으로 본체를 조심스럽게 평행하게 들어 올려 평평한 바닥으로 안전하게 옮겨주어야 합니다.',
    '물걸레판을 분리할 수 있는 구조의 모델에 한하여, 일반 먼지 흡입 청소 모드에서만 물걸레판을 탈거한 뒤 문턱을 원활하게 넘는지 시험해볼 수 있습니다.',
    '마그네틱 센서를 지원하는 기기라면 물리적인 진입 방지 테이프를 바닥에 부착해 통과를 차단할 수 있으며, 라이다 센서 기반의 최신 스마트 모델이라면 전용 모바일 앱의 맵 관리 화면에서 가상 벽이나 청소 금지 구역을 설정하여 로봇청소기가 해당 문턱 구역으로 접근하지 않도록 사전에 예방 조치를 취하는 것이 안전합니다.'
]
# Synthetic documentation fixtures, not a factual review of the user's account.
GOOD=[
    '이 예제 모델의 점검 표시는 제품 설명서의 코드 안내와 함께 확인합니다.',
    '예제 제품 안내에서는 이동 전에 해당 제품의 비상 스위치를 끄도록 설명합니다.',
    '이 안내의 이동 절차는 해당 예제 모델에 한하여 적용합니다.',
    '예제 설명서에서는 바퀴 이물질 점검 전에 전원을 끄도록 안내합니다.',
    '이 예제 모델의 가상 경계 설정은 해당 제품의 앱 안내에서 확인합니다.'
]
FIG1='<figure><img src="https://lh3.googleusercontent.com/a" alt="첫 번째 이미지"><figcaption>그림 1. 첫 번째 장면을 보여 주는 설명입니다.</figcaption></figure>'
FIG2='<figure><img src="https://lh3.googleusercontent.com/b" alt="두 번째 이미지"><figcaption>그림 2. 두 번째 장면을 보여 주는 설명입니다.</figcaption></figure>'

def diagnostic():
    return {'reason':'EVIDENCE_ORIGINALS_INCOMPLETE','summary':'원문으로 지원되지 않는 핵심 사실',
            'unverified_claims':[{'text':s,'reason':'연결된 원문에서 직접 지원하지 않음'} for s in BAD]}
def content():
    normal=''.join('보존할 기존 설명 문장 '+str(i)+'은 해당 주제의 정상 문단으로 유지됩니다. ' for i in range(55))
    return '<h2>상태 확인</h2><p>'+normal+' '.join(GOOD)+'</p>'+''.join('<p>'+s+'</p>'+(FIG1 if i==0 else FIG2 if i==3 else '') for i,s in enumerate(BAD))+'<h2>마지막 점검</h2><p>이 정상 문단도 보존합니다.</p>'
def ledger(initial=False):
    sources=[{'id':'s1','url':'https://maker.example/manual?id=7','grade':'A'},
             {'id':'s2','url':'https://agency.example/guide','grade':'A'}]
    facts=[{'id':'f'+str(i),'text':v,'source_ids':['s1' if i%2==0 else 's2'],
            'core':i<2,'kind':['core','core','practical','condition','other'][i]}
           for i,v in enumerate(GOOD)]
    if initial:
        facts += [{'id':'bad'+str(i),'text':v,'source_ids':['s1'],'core':True,'kind':'core'} for i,v in enumerate(BAD)]
    return {'sources':sources,'facts':facts,'retrieved_at':now()}
class Reader:
    def read_many(self,sources,progress):
        text=' '.join(GOOD)
        return {s['id']:{'status':'FETCHED','text':text,'text_hash':digest(text),'final_url':s['url'],'checked_at':now()} for s in sources}
class AI:
    model='fixture'
    def __init__(self,mode='good'):self.mode=mode;self.repairs=0;self.images=0;self.requests=[]
    def structured_object(self,prompt,schema):
        self.requests.append(prompt)
        if prompt.startswith('R3 FINAL EVIDENCE PARAGRAPH REPAIR:'):
            self.repairs+=1
            inputs=json.loads(prompt.split('\n',1)[1])
            if self.mode=='cancel':
                from r3studio.tasks import Cancelled
                raise Cancelled('중단')
            edits=[{'block_id':b['block_id'],'new_html':'<p>'+GOOD[i]+'</p>','reason':'지원되지 않는 확장 설명을 원문 적용 조건으로 수정'}
                   for i,b in enumerate(inputs['blocks'])]
            if self.mode=='malformed':edits[0]['block_id']='outside'
            if self.mode=='unchanged':edits[0]['new_html']=inputs['blocks'][0]['old_html']
            return {'edits':edits}
        data=json.loads(prompt.split('\n',1)[1]);facts=data['facts']
        claims=[]
        for f in facts:
            good=f['text'] in GOOD
            if self.mode=='unsupported':good=False
            claims.append({'fact_id':f['id'],'source_id':f['source_ids'][0],
                           'supported':good,'quote':f['text'] if good else ''})
        return {'claims':claims,'sources':[{'source_id':'s1','grade':'A','publisher':'예제 제조사'},
                                          {'source_id':'s2','grade':'A','publisher':'예제 독립 기관'}]}
    def image_object(self,prompt,data,mime):
        self.images+=1
        if self.mode=='pixel_fail':return {'relevant':False}
        return {k:True for k in ('relevant','visual_quality','single_scene','no_overlay_text','safe_depiction','alt_match','caption_match')}

class Tests(unittest.TestCase):
    def test_targets_all_five_user_claims_without_captions_or_other_paragraphs(self):
        c=content();blocks=paragraph_targets(c,diagnostic())
        self.assertEqual(len(blocks),5)
        answer={'edits':[{'block_id':b['block_id'],'new_html':'<p>'+GOOD[i]+'</p>','reason':'조건 수정'} for i,b in enumerate(blocks)]}
        result,edits=apply_answer(c,blocks,answer)
        self.assertEqual(Document(result).images,Document(c).images)
        self.assertIn(FIG1,result);self.assertIn(FIG2,result)
        self.assertIn('<p>이 정상 문단도 보존합니다.</p>',result)
        self.assertFalse(any(v in result for v in BAD))
        self.assertEqual(len(edits),5)
    def test_stale_or_caption_only_claim_is_not_a_prose_edit(self):
        for c in (content().replace(BAD[0],'현재 본문에서 달라진 문장입니다.'),
                  content().replace('<p>'+BAD[0]+'</p>','<figure><img src="x"><figcaption>'+BAD[0]+'</figcaption></figure>')):
            with self.assertRaises(EvidenceHold):paragraph_targets(c,diagnostic())
    def test_missing_duplicate_unchanged_and_unrequested_edits_rejected(self):
        blocks=paragraph_targets(content(),diagnostic())
        valid=[{'block_id':b['block_id'],'new_html':'<p>'+GOOD[i]+'</p>','reason':'조건 수정'} for i,b in enumerate(blocks)]
        for edits in (valid[:-1],valid+[valid[0]],[],[{**v,'block_id':'wrong'} for v in valid],
                      [{**v,'new_html':blocks[i]['old_html']} for i,v in enumerate(valid)]):
            with self.assertRaises(EvidenceHold):apply_answer(content(),blocks,{'edits':edits})
    def test_script_image_new_link_and_heading_in_edits_are_rejected(self):
        blocks=paragraph_targets(content(),diagnostic())
        for bad in ('<p onclick="x()">설명</p>','<p><img src="x"></p>','<p><a href="https://new.example">새 링크</a></p>','<h2>새 제목</h2>'):
            edits=[{'block_id':b['block_id'],'new_html':'<p>'+GOOD[i]+'</p>','reason':'조건 수정'} for i,b in enumerate(blocks)]
            edits[0]['new_html']=bad
            with self.assertRaises(EvidenceHold):apply_answer(content(),blocks,{'edits':edits})
    def test_research_keeps_faq_document_id_while_display_redacts_query(self):
        url='https://help.ecovacs.com/kr/support/faq-detail?id=991&product_id=5'
        self.assertEqual(ArticleContext('<a href="'+url+'">설명</a>').context()['existing_urls'],[url])
        self.assertNotIn('id=',display_url(url))
    def test_original_context_never_uses_altered_or_missing_originals(self):
        pack=ledger();pack['evidence_review']={'originals':Reader().read_many(pack['sources'],lambda *a:None)}
        self.assertIn('?id=7',original_context(pack)['originals']['s1']['url'])
        for value in pack['evidence_review']['originals'].values():value['text']='변경된 원문'
        with self.assertRaises(EvidenceHold):original_context(pack)
    def fixture(self,d,mode='good'):
        s,server,adapter,service,pid=uploads.Tests().fixture(d)
        _,p=service.load(pid)
        p.update(mode='REPLACEMENT',replacement_preview_ready=True,proposed_content=content(),proposed_title='예제 점검 글')
        ai=AI(mode);service.ai=ai
        for k,choice in p['image_choices'].items():
            choice['candidate']['target']={'slot':int(k),'url':choice['expected_url'],'article_hash':digest(p['proposed_content'])}
        initial=ledger(True)
        with self.assertRaises(EvidenceHold) as caught:verify_origins(AI(),initial,Reader())
        p.update(error_diagnostic=caught.exception.diagnostic,final_evidence_pack=caught.exception.partial_pack)
        p['final_evidence_for']=signature(p)
        service.save(pid,p)
        return s,server,service,pid,ai,copy.deepcopy(p)
    def checks(self,service,mode='good'):
        stack=ExitStack()
        stack.enter_context(patch('r3studio.evidence.Research.collect',return_value=ledger()))
        stack.enter_context(patch('r3studio.sources.SourceReader',return_value=Reader()))
        def refs(ai,title,c,peers,pack,strict=False,record=lambda v:None):
            require_originals(pack)
            record({'body_hash':digest(c),'references':[]})
            return c
        stack.enter_context(patch('r3studio.links.append_verified_candidates',side_effect=refs))
        stack.enter_context(patch('r3studio.article_policy.generated_fast',return_value=Result('NEEDS_DEEP','DEEP',[],{})))
        stack.enter_context(patch('r3studio.fact_search.collect',return_value={}))
        stack.enter_context(patch('r3studio.repair_images.evaluate',return_value={'text_verified':mode!='deep_fail','review':{'fact':'FAIL','issues':['추가 사실 문제'],'unsupported_claims':['수정 문장 확인 필요']}}))
        stack.enter_context(patch('r3studio.repair_images.check_public_images',return_value=[{'result':'PASS'},{'result':'PASS'}]))
        stack.enter_context(patch('r3studio.finalize.decide',return_value={'ready':True}))
        stack.enter_context(patch('r3studio.repair_images.check_links',return_value={'pass':True}))
        stack.enter_context(patch('r3studio.repair_images.Apply.prepare',side_effect=lambda *args:{
            'expected_hash':service.load(1)[1]['expected_hash'],'expected_updated':'v1','expected_url':'https://blog.example/post',
            'proposal':{'title':args[1],'content':args[2],'labels':[]}}))
        return stack
    def test_real_final_hold_to_prose_repair_and_pass_retains_uuid_pixels_and_schedule(self):
        with tempfile.TemporaryDirectory() as d:
            s,server,service,pid,ai,before=self.fixture(d)
            with self.checks(service):result=service.repair_evidence(pid)
            self.assertEqual(result['status'],'PASS',result.get('reason'))
            self.assertEqual(ai.repairs,1);self.assertEqual(ai.images,2)
            self.assertEqual(server.uploads,[uploads.RID,uploads.RID2])
            self.assertEqual(result['before'],before['before'])
            self.assertEqual(result['proposed_title'],before['proposed_title'])
            for k in ('1','2'):
                old=before['image_choices'][k];new=result['image_choices'][k]
                self.assertEqual(new['request_id'],old['request_id'])
                self.assertEqual(new['candidate']['info'],old['candidate']['info'])
                self.assertEqual(new['candidate']['alt'],old['candidate']['alt'])
                self.assertEqual(new['candidate']['caption'],old['candidate']['caption'])
                self.assertTrue(new['receipt']['ok'])
            require_originals(result['evidence'])
            self.assertIn('보완 전:',report(result));self.assertIn('보완 후:',report(result))
            self.assertEqual(result['final_text_versions'][0]['content'],before['proposed_content'])
            # Final validation repeats reuse DONE receipts, never repeat uploads.
            with self.checks(service):again=service.validate(pid)
            self.assertEqual(again['status'],'PASS')
            self.assertEqual(server.uploads,[uploads.RID,uploads.RID2])
            s.close()
    def test_rejected_response_preserves_current_body_images_and_never_uploads(self):
        for mode in ('malformed','unchanged','pixel_fail','unsupported'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                s,server,service,pid,ai,before=self.fixture(d,mode)
                with self.checks(service):result=service.repair_evidence(pid)
                self.assertEqual(result['status'],'HOLD')
                self.assertEqual(result['proposed_content'],before['proposed_content'])
                self.assertEqual(result['image_choices'],before['image_choices'])
                self.assertEqual(server.uploads,[])
                self.assertNotIn('plan',result)
                self.assertEqual(ai.repairs,1)
                s.close()
    def test_final_quality_failure_keeps_corrected_candidate_but_no_apply_plan(self):
        with tempfile.TemporaryDirectory() as d:
            s,server,service,pid,ai,before=self.fixture(d)
            with self.checks(service,'deep_fail'):result=service.repair_evidence(pid)
            self.assertEqual(result['status'],'HOLD')
            self.assertNotEqual(result['proposed_content'],before['proposed_content'])
            self.assertEqual(result['error_diagnostic']['reason'],'REPLACEMENT_TEXT_HOLD')
            self.assertIn('추가 사실 문제',report(result))
            self.assertEqual(result['final_text_repairs'][-1]['state'],'APPLIED_HOLD')
            self.assertNotIn('plan',result);s.close()
    def test_cancellation_does_not_destroy_approved_body_or_images(self):
        from r3studio.tasks import Cancelled
        with tempfile.TemporaryDirectory() as d:
            s,server,service,pid,ai,before=self.fixture(d,'cancel')
            with self.checks(service),self.assertRaises(Cancelled):service.repair_evidence(pid)
            saved=service.load(pid)[1]
            self.assertEqual(saved['proposed_content'],before['proposed_content'])
            self.assertEqual(saved['image_choices'],before['image_choices'])
            self.assertEqual(saved['final_text_repairs'][-1]['state'],'CANCELLED')
            self.assertFalse(server.uploads);s.close()
    def test_resume_routes_final_evidence_hold_to_prose_repair_before_generation(self):
        from r3studio.replacement import Replacement
        with tempfile.TemporaryDirectory() as d:
            s,server,service,pid,ai,before=self.fixture(d)
            replacement=Replacement(s,service.adapter,ai,d)
            with patch.object(replacement.images,'repair_evidence',return_value={'marker':'repair'}) as called:
                result=replacement.resume(pid,None)
            self.assertEqual(result,{'marker':'repair'});called.assert_called_once_with(pid);s.close()
    def test_repair_action_requires_text_model_but_no_image_generation_model(self):
        self.assertIn('repair_evidence',AI_ACTIONS)
        require_settings({'R3_BLOG_ID':'1','R3_BRIDGE_URL':uploads.URL,'R3_BRIDGE_SECRET':'x','R3_GEMINI_KEY':'x','R3_GEMINI_MODEL':'fixture'},'repair_evidence')

if __name__=='__main__':unittest.main()
