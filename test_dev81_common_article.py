"""Dev81 shared prose/reference/layout policy and upgrade preservation."""
import json,tempfile,unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from r3studio.article_policy import *
from r3studio.references import select,document_label,verify_binding_content
from r3studio.links import append_verified_candidates
from r3studio.evidence import EvidenceHold
from r3studio.generation import Generation
from r3studio.sources import SourceReader
from r3studio.sync import digest
from r3studio.layout import compose,LayoutHold
from r3studio.text_flow import ready,report
from r3studio.replacement import Replacement
from r3studio.imagegen import generate_candidates
from test_generation import pack
import test_dev70_replacement as fixture
from test_dev78_saved_body import AI,seed
from test_dev75_original_refill import AI as OriginalAI,QUOTE,TITLE

def long_body(topic='제품'):
    return '<h2>'+topic+' 상태 확인</h2><p>'+''.join(topic+' 점검 '+str(i)+'에서는 제품 설명서의 적용 조건과 허용된 사용 범위를 확인합니다. ' for i in range(30))+'</p><h2>이동 조건</h2><p>모델별 안내를 확인합니다.</p><h2>바퀴 센서 청소</h2><p>바퀴와 센서의 점검 조건을 설명합니다.</p><h2>후속 조치</h2><p>설명서의 문제 해결 항목을 확인합니다.</p>'

def choices(content,p=None):
    p=p or pack();c=p['original_verification']['claims'][0]
    return {'ids':['2'],'references':[{'source_id':c['source_id'],'fact_id':c['fact_id'],'excerpt':body_text(content)[:100]}]}

class ChoiceAI:
    def __init__(self,mode='ok'):self.calls=[];self.mode=mode
    def object(self,prompt):
        self.calls.append(prompt);data=json.loads(prompt.rsplit('\n',1)[1])
        answer=choices(data['article'])
        if self.mode=='unused':answer['references'][0]['source_id']='unused'
        if self.mode=='bad_once' and len(self.calls)==1:answer['references'][0]['excerpt']='본문에 없는 문장을 절대로 출처 연결로 사용해서는 안 됩니다.'
        return answer

class Tests(unittest.TestCase):
    def test_prose_excludes_captions_alt_related_and_references_for_any_topic(self):
        for topic in ('로봇청소기','보조 배터리','벽 재질','가전 제품'):
            with self.subTest(topic=topic):
                content='<h2>'+topic+' 확인</h2><p>사용 조건을 확인합니다.</p>'
                extra='<figure><img src="https://image.example/a" alt="'+('ALT '*1000)+'"><figcaption>'+('그림 설명 '*1000)+'</figcaption></figure>'
                extra+='<section data-r3-kind="related"><h2>함께 읽으면 도움이 되는 글</h2><p>'+('관련 글 '*1000)+'</p></section>'
                extra+='<section data-r3-kind="references"><h2>참고 자료</h2><p>'+('참고 자료 '*1000)+'</p></section>'
                self.assertEqual(body_metrics(content)['body_text_length'],body_metrics(content+extra)['body_text_length'])
                self.assertGreater(body_metrics(content+extra)['body_deficit'],0)
                self.assertIn('본문 길이 검토 필요',generated_fast({'id':'NEW','title':topic,'content':content+extra,'status':'DRAFT'}).issues)

    def test_legacy_unmarked_lists_do_not_inflate_prose_or_survive_reconnection(self):
        body=long_body();full=body+'<h2>함께 읽으면 도움이 되는 글</h2><ul><li>관련</li></ul><h2>참고 자료</h2><ul><li>근거 자료 9</li></ul>'
        self.assertEqual(body_text(full),body_text(body))
        self.assertNotIn('근거 자료 9',strip_auxiliary(full))
        self.assertEqual(body_text(strip_auxiliary(full)),body_text(body))

    def test_reference_selection_only_uses_original_backed_fact_and_actual_excerpt(self):
        p=pack();p['sources'].append({'id':'unused','url':'https://unused.example/video','grade':'A','reason':'모든 곳에 붙이면 안 되는 영상'})
        p['original_verification']['pack_hash']=digest({'sources':p['sources'],'facts':p['facts']})
        p['original_verification']['originals'][p['original_verification']['claims'][0]['source_id']]['document_title']='제조사 모델별 사용 설명서'
        body=long_body();records=[]
        result=append_verified_candidates(ChoiceAI(),TITLE,body,[{'post_id':'2','title':'관련 점검','url':'https://blog.example/peer','status':'LIVE'}],p,strict=True,record=records.append)
        self.assertIn('제조사 모델별 사용 설명서',result)
        self.assertNotIn('unused.example',result);self.assertNotIn('근거 자료 5',result)
        self.assertIn('본문에서 확인한 내용',result);self.assertEqual(len(records[0]['references']),1)
        verify_binding_content(result,records[0])
        with self.assertRaises(EvidenceHold):verify_binding_content(result.replace('모델별 안내','다른 안내'),records[0])

    def test_reference_retry_reuses_same_article_and_originals_only_once(self):
        ai=ChoiceAI('bad_once');body=long_body();posts=[{'post_id':'2','title':'관련','url':'https://blog.example/peer','status':'LIVE'}]
        result=append_verified_candidates(ai,TITLE,body,posts,pack(),strict=True)
        self.assertEqual(len(ai.calls),2);self.assertIn('R3 REFERENCE BINDING REPAIR',ai.calls[1])
        self.assertIn('본문에서 확인한 내용',result)
        ai=ChoiceAI('unused')
        with self.assertRaises(EvidenceHold):append_verified_candidates(ai,TITLE,body,posts,pack(),strict=True)
        self.assertEqual(len(ai.calls),2)

    def test_unsupported_fact_unmatched_excerpt_or_invented_source_is_rejected(self):
        body=long_body();p=pack();good=choices(body)
        for key,value in [('fact_id','unknown'),('source_id','unknown'),('excerpt','없는 문장이라면 어떤 출처도 붙여서는 안 됩니다.')]:
            with self.subTest(key=key):
                bad=deepcopy(good);bad['references'][0][key]=value
                with self.assertRaises(EvidenceHold):select(bad,body,p)

    def test_title_unavailable_uses_real_domain_path_not_grade_reason(self):
        p=pack();p['sources'][0]['reason']='공식 영상이라서 A등급'
        self.assertEqual(document_label(p['sources'][0],p),'manufacturer.example/manual')

    def test_fetched_html_document_title_is_preserved_without_extra_network_request(self):
        with tempfile.TemporaryDirectory() as d:
            s=fixture.Store(d+'/db');calls=[]
            def fetch(url):
                calls.append(url);return {'status':200,'url':url,'headers':{'content-type':'text/html'},'body':'<title>모델별 &amp; 점검 안내</title><p>'+QUOTE*20+'</p>'}
            reader=SourceReader(s,fetch);r=reader.read('https://maker.example/manual');again=reader.read('https://maker.example/manual')
            self.assertEqual(r['document_title'],'모델별 & 점검 안내');self.assertEqual(len(calls),1);self.assertEqual(again['document_title'],r['document_title']);s.close()

    def test_two_figures_attach_to_distinct_relevant_sections_before_references(self):
        body=long_body();body+='<section data-r3-kind="related"><h2>함께 읽으면 도움이 되는 글</h2><p>관련</p></section><section data-r3-kind="references"><h2>참고 자료</h2><p>자료</p></section>'
        blocks=['<figure><img src="local:1" alt="상태"><figcaption>상태 예시</figcaption></figure>','<figure><img src="local:2" alt="바퀴"><figcaption>바퀴 점검 예시</figcaption></figure>']
        images=[{'placement_section':1},{'placement_section':3}]
        output=place_figures(body,blocks,images)
        self.assertLess(output.index('local:1'),output.index('<h2>이동 조건'))
        self.assertGreater(output.index('local:2'),output.index('<h2>바퀴 센서 청소'))
        self.assertLess(output.index('local:2'),output.index('<h2>후속 조치'))
        self.assertLess(output.index('local:2'),output.index('<h2>참고 자료'))
        self.assertEqual(body_text(output),body_text(body));self.assertEqual(Document(output).errors,[])

    def test_invalid_or_duplicate_section_number_cannot_attach_to_references(self):
        for images in ([{'placement_section':99},{'placement_section':2}],[{'placement_section':1},{'placement_section':1}]):
            with self.assertRaises(ValueError):place_figures(long_body(),['<figure></figure>']*2,images)

    def test_new_publication_compose_uses_same_relevant_section_placement(self):
        c=[{'result':'PASS','info':{'byte_hash':'abc'},'alt':'상태','caption':'상태 예시','placement_section':1},
           {'result':'PASS','info':{'byte_hash':'def'},'alt':'바퀴','caption':'바퀴 예시','placement_section':3}]
        r=[{'ok':True,'publicImageUrl':'https://lh3.googleusercontent.com/one','byte_hash':'abc'},
           {'ok':True,'publicImageUrl':'https://lh3.googleusercontent.com/two','byte_hash':'def'}]
        output=compose(long_body(),c,r)
        self.assertGreater(output.index('/two'),output.index('<h2>바퀴 센서 청소'))
        self.assertLess(output.index('/two'),output.index('<h2>후속 조치'))

    def test_upgrade_keeps_existing_job_and_pixels_but_reaudits_body_and_layout(self):
        with tempfile.TemporaryDirectory() as d:
            ai=AI('all_pass');s,a,svc,r,before=seed(d,ai);gen=fixture.Generator()
            first=svc.resume(r['proposal_id'],gen);self.assertTrue(first.get('replacement_preview_ready'),first.get('reason'))
            files=[v['file'] for v in first['image_edit_candidates'].values()]
            _,old=svc.images.load(r['proposal_id']);old.pop('article_policy',None);svc.images.save(r['proposal_id'],old)
            audits=ai.audits;count=len(gen.calls)
            updated=svc.resume(r['proposal_id'],gen)
            self.assertTrue(updated.get('replacement_preview_ready'),updated.get('reason'))
            self.assertEqual(updated['replacement_job_id'],r['replacement_job_id']);self.assertEqual(updated['before']['id'],'1')
            self.assertGreater(ai.audits,audits);self.assertEqual(len(gen.calls),count)
            self.assertEqual([v['file'] for v in updated['image_edit_candidates'].values()],files)
            self.assertTrue(all(v.get('reused_after_body_review') for v in updated['image_edit_candidates'].values()))
            self.assertIn('본문에 실제 연결한 참고 자료',report(updated))
            self.assertLess(updated['proposed_content'].rindex('<figure'),updated['proposed_content'].index('<section data-r3-kind="related"'))
            self.assertEqual(a.get_post('1')['content'],updated['before']['content']);self.assertNotIn('plan',updated);s.close()

    def test_upgrade_preserves_unconfirmed_upload_journal_without_regenerating(self):
        with tempfile.TemporaryDirectory() as d:
            ai=AI('all_pass');s,a,svc,r,before=seed(d,ai);gen=fixture.Generator()
            first=svc.resume(r['proposal_id'],gen)
            _,old=svc.images.load(r['proposal_id']);old.pop('article_policy',None)
            old['image_choices']['1']['request_id']='pending-upload'
            svc.images.save(r['proposal_id'],old)
            count=len(gen.calls);audits=ai.audits
            result=svc.resume(r['proposal_id'],gen)
            self.assertIn('업로드 결과 미확정',result['reason'])
            self.assertEqual(result['image_choices']['1']['request_id'],'pending-upload')
            self.assertEqual(len(gen.calls),count);self.assertEqual(ai.audits,audits)
            self.assertEqual(result['proposed_content'],first['proposed_content']);s.close()

    def test_success_flags_cannot_override_short_prose_with_long_reference_list(self):
        p={'content':'<h2>확인</h2><p>본문이 짧습니다.</p><h2>참고 자료</h2><p>'+('자료 '*1000)+'</p>',
           'deep':{'review':deepcopy(fixture.REVIEW)},'fast':{'issues':[]}}
        self.assertFalse(ready(p))

    def test_fact_boundary_rules_are_common_not_robot_specific(self):
        from r3studio.origin_response import request_review
        from r3studio.deep import evaluate
        p=pack();seen=[]
        class ReviewAI:
            def object(self,prompt):
                seen.append(prompt)
                if 'claims:[{fact_id' in prompt:
                    return {'claims':p['original_verification']['claims'],'sources':[{'source_id':s['id'],'grade':'A','publisher':s['id']} for s in p['sources']]}
                return deepcopy(fixture.REVIEW)
        ai=ReviewAI();request_review(ai,{'facts':p['facts'],'sources':p['sources'],'originals':p['original_verification']['originals']})
        evaluate(ai,{'status':'DRAFT','title':'보조 배터리 사용 조건','content':long_body('배터리')},p,{'issues':[]},text_only=True)
        for prompt in seen:self.assertIn('이상/이하와 이내/이후',prompt);self.assertIn('선행 조건·순서·금지 사항',prompt)

    def test_new_article_uses_same_saved_prose_repair_before_image_stage(self):
        class NewAI(OriginalAI):
            repairs=0
            def object(self,prompt):
                if '제목 하나' in prompt:return {'title':TITLE}
                if '블로그 글을 작성하세요' in prompt:
                    return {'content_html':'<h2>'+TITLE+'</h2><p>'+''.join('점검 항목 '+str(i)+'에서 모델별 설명서의 사용 조건을 확인합니다. ' for i in range(40))+'</p><h2>확인 조건</h2><p>설명서의 점검 항목을 확인합니다.</p>','search_description':'제품 설명서와 상태를 확인하는 점검 안내'}
                if 'R3 SAVED BODY PARTIAL REPAIR' in prompt:
                    self.repairs+=1
                    return {'edits':[{'old_html':'<h2>확인 조건</h2>','new_html':'<h2>확인 조건</h2><p>'+''.join('확인 조건 '+str(i)+'에 따른 제품 설명서의 점검 순서와 적용 범위를 대조합니다. ' for i in range(25))+'</p>','reason':'검증된 적용 조건과 부족한 설명 보완'}]}
                return super().object(prompt)
        with tempfile.TemporaryDirectory() as d:
            s,a,pid=fixture.Tests().setup_case(d);ai=NewAI()
            reader=SourceReader(s,lambda url:{'status':200,'url':url,'headers':{'content-type':'text/html'},'body':'<p>'+QUOTE*20+'</p>'})
            g=Generation(s,ai,'blog',source_reader=reader);r=g.generate(TITLE);p=g.load_job(r['job_id'])['payload']
            self.assertEqual(r['stage'],'이미지·링크 검사 대기',r.get('reason'));self.assertGreater(ai.repairs,0)
            self.assertTrue(ready(p));self.assertEqual(p['article_policy'],VERSION)
            self.assertGreaterEqual(body_metrics(p['content'])['body_text_length'],MIN_BODY_LENGTH)
            self.assertTrue(p['text_versions']);self.assertNotIn('image_candidates',p);s.close()

if __name__=='__main__':unittest.main()
