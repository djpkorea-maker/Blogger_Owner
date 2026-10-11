"""Dev78 uncited Fact reply regression through real Gemini parsing and resume."""
import json,tempfile,unittest
from copy import deepcopy
from unittest.mock import patch
import test_dev70_replacement as fixture
from test_dev78_saved_body import AI,seed
from test_dev75_original_refill import TITLE
from test_generation import pack
from r3studio.ai import Gemini,AIError
from r3studio.fact_search import collect,valid_citations
from r3studio.generation import Generation
from r3studio.text_flow import report
from r3studio.gates import Document
from r3studio.tasks import Cancelled
from r3studio.sync import digest
from r3studio.evidence import EvidenceHold
from r3studio.presentation import diagnostic_lines

def response(kind):
    steps=[]
    if kind in ('result','error','cited'):
        steps=[{'type':'google_search_call','id':'q1','arguments':{'queries':['official manual']}},
               {'type':'google_search_result','call_id':'q1','is_error':kind=='error','result':[{'search_suggestions':'<a href="https://invented.example">suggestion is not evidence</a>'}]}]
    annotations=[{'type':'url_citation','url':s['url'],'title':'Official manual'} for s in pack()['sources']] if kind=='cited' else []
    steps.append({'type':'model_output','content':[{'type':'text','text':'검증 결과 요약입니다. https://invented.example/ is model prose.',
                                                 'annotations':annotations}]})
    return {'status':'completed','steps':steps}

class SearchAI(AI):
    def __init__(self,kinds,mode='all_pass'):
        super().__init__(mode);self.kinds=list(kinds);self.search_calls=[];self.transport_calls=[]
        self.client=Gemini('not-a-real-key','gemini-3.8-flash',self.transport)
    def transport(self,payload):
        self.transport_calls.append(deepcopy(payload))
        kind=self.kinds.pop(0)
        if isinstance(kind,Exception):raise kind
        return response(kind)
    def ask(self,prompt,*args,**kwargs):
        if '저장된 본문의 핵심 사실' in prompt or 'R3 FACT SEARCH CITATION RECOVERY' in prompt:
            self.audits+=1;self.search_calls.append((prompt,kwargs))
            return self.client.ask(prompt,*args,**kwargs)
        return super().ask(prompt,*args,**kwargs)

class Tests(unittest.TestCase):
    def test_uncited_actual_response_recovers_then_preserves_body_and_generates_two_images(self):
        with tempfile.TemporaryDirectory() as d:
            ai=SearchAI(['none','cited']);s,a,svc,r,before=seed(d,ai);generator=fixture.Generator()
            with patch.object(Generation,'resume',side_effect=AssertionError('전체 Writer 호출 금지')):
                out=svc.resume(r['proposal_id'],generator)
            self.assertTrue(out.get('replacement_preview_ready'),out.get('reason'))
            self.assertEqual(out['replacement_job_id'],r['replacement_job_id'])
            self.assertEqual(out['text_versions'][0]['content'],before['content'])
            self.assertEqual(ai.repairs,0);self.assertEqual(ai.writers,[])
            self.assertEqual(len(ai.search_calls),2);self.assertEqual(ai.search_calls[1][1]['timeout_seconds'],60)
            self.assertEqual([x['citation_count'] for x in out['fact_search_attempts']],[0,2])
            self.assertEqual(out['fact_search_attempts'][0]['search_execution'],'NOT_OBSERVED')
            self.assertEqual(out['fact_search_attempts'][1]['search_execution'],'CITED')
            self.assertNotIn('tool_choice',ai.transport_calls[1].get('generation_config',{}))
            self.assertEqual(len(generator.calls),2);self.assertEqual(len(Document(out['proposed_content']).images),2)
            self.assertTrue(out['image_pipeline']['generation_started'])
            self.assertEqual(out['image_pipeline']['status'],'READY')
            self.assertIn('출처 0개',report(out));self.assertIn('출처 2개',report(out))
            self.assertEqual(a.get_post('1')['content'],out['before']['content']);self.assertNotIn('plan',out);s.close()

    def test_two_uncited_replies_hold_before_image_api_without_old_deep_pass(self):
        for kind,label in [('none','실행 기록 없음'),('result','출처 인용 누락'),('error','검색 도구 오류')]:
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as d:
                ai=SearchAI([kind,kind]);s,a,svc,r,before=seed(d,ai);generator=fixture.Generator()
                out=svc.resume(r['proposal_id'],generator)
                self.assertEqual(out['proposed_content'],before['content']);self.assertFalse(out.get('replacement_preview_ready'))
                self.assertEqual(out['error_diagnostic']['reason'],'FACT_SEARCH_UNCITED');self.assertIn(label,out['reason'])
                self.assertIn('이미지 생성 시작 전',out['reason']);self.assertFalse(out['image_pipeline']['generation_started'])
                self.assertEqual(len(ai.search_calls),2);self.assertEqual(generator.calls,[]);self.assertEqual(ai.repairs,0)
                payload=Generation(s,ai,'blog').load_job(r['replacement_job_id'])['payload']
                self.assertNotIn('deep',payload);self.assertNotIn('independent_fact_search',payload)
                self.assertNotIn('generation_text_review',out);s.close()

    def test_search_auth_quota_timeout_and_invalid_json_do_not_trigger_uncited_retry(self):
        for reason in ('UNAUTHENTICATED','RESOURCE_EXHAUSTED','TIMEOUT','INVALID_JSON'):
            with self.subTest(reason=reason),tempfile.TemporaryDirectory() as d:
                ai=SearchAI([AIError('API 연결 오류',{'reason':reason,'summary':'연결 오류'})])
                s,a,svc,r,before=seed(d,ai);generator=fixture.Generator();out=svc.resume(r['proposal_id'],generator)
                self.assertEqual(len(ai.search_calls),1);self.assertEqual(out['error_diagnostic']['reason'],reason)
                self.assertEqual(out['proposed_content'],before['content']);self.assertEqual(generator.calls,[]);s.close()

    def test_second_search_timeout_preserves_both_attempts_and_exact_stage(self):
        with tempfile.TemporaryDirectory() as d:
            ai=SearchAI(['result',AIError('검색 대기 시간 초과',{'reason':'TIMEOUT','summary':'응답 시간 초과'})])
            s,a,svc,r,before=seed(d,ai);out=svc.resume(r['proposal_id'],fixture.Generator())
            self.assertEqual(out['error_diagnostic']['reason'],'TIMEOUT')
            self.assertEqual([x['state'] for x in out['fact_search_attempts']],['UNCITED','CONNECTION_ERROR'])
            self.assertIn('집중 검색 1회',out['error_diagnostic']['stage']);self.assertEqual(out['proposed_content'],before['content'])
            self.assertIn('TIMEOUT','\n'.join(diagnostic_lines(out['error_diagnostic'])));s.close()

    def test_real_annotation_contract_never_accepts_prose_suggestions_or_invalid_urls(self):
        for bad in (None,'not-a-list',[None],[{'type':'url_citation','url':'https://key:secret@example.com/path'}],
                    [{'type':'url_citation','url':'javascript:alert(1)'}],[{'type':'url_citation','url':[]}]):
            raw=response('result');raw['steps'][-1]['content'][0]['annotations']=bad
            value=Gemini('key','model',lambda p:raw).ask('query',search=True)
            self.assertEqual(value['citations'],[]);self.assertEqual(value['search_diagnostic']['execution'],'RESULT_WITHOUT_CITATIONS')
            self.assertNotIn('secret',json.dumps(value['search_diagnostic']))
        value=Gemini('key','model',lambda p:response('cited')).ask('query',search=True)
        self.assertEqual(len(value['citations']),2)

    def test_cancel_before_recovery_keeps_body_and_stops_second_search(self):
        with tempfile.TemporaryDirectory() as d:
            ai=SearchAI(['none','cited']);s,a,svc,r,before=seed(d,ai)
            def progress(stage,*args):
                if '출처 누락 집중 검색' in stage:raise Cancelled('사용자 중단')
            svc.progress=progress
            with self.assertRaises(Cancelled):svc.resume(r['proposal_id'],fixture.Generator())
            payload=Generation(s,ai,'blog').load_job(r['replacement_job_id'])['payload']
            self.assertEqual(len(ai.search_calls),1);self.assertEqual(payload['content'],before['content']);s.close()

    def test_citations_do_not_override_factual_unknown_or_trigger_image_cost(self):
        with tempfile.TemporaryDirectory() as d:
            ai=SearchAI(['none','cited','cited'],'still_fail');s,a,svc,r,before=seed(d,ai);generator=fixture.Generator()
            out=svc.resume(r['proposal_id'],generator)
            self.assertFalse(out.get('replacement_preview_ready'));self.assertEqual(generator.calls,[])
            self.assertEqual(ai.repairs,1);self.assertEqual(out['error_diagnostic']['text_review']['states']['fact'],'UNKNOWN');s.close()

    def test_repaired_body_runs_its_own_search_recovery_not_previous_body_results(self):
        with tempfile.TemporaryDirectory() as d:
            ai=SearchAI(['none','cited','none','cited'],'good');s,a,svc,r,before=seed(d,ai);generator=fixture.Generator()
            out=svc.resume(r['proposal_id'],generator)
            self.assertTrue(out.get('replacement_preview_ready'),out.get('reason'))
            self.assertEqual(ai.repairs,1);self.assertEqual(len(ai.search_calls),4)
            payload=Generation(s,ai,'blog').load_job(r['replacement_job_id'])['payload']
            # Links are added after text review; search is bound to the repaired text before that addition.
            self.assertNotEqual(payload['independent_fact_search']['article_hash'],
                                digest({'title':before['title'],'content':before['content']}))
            self.assertEqual(len(generator.calls),2);s.close()

    def test_initial_search_failure_does_not_recursively_resume_saved_body_in_same_run(self):
        with tempfile.TemporaryDirectory() as d:
            s,a,pid=fixture.Tests().setup_case(d);ai=SearchAI(['none','cited'])
            from r3studio.replacement import Replacement
            svc=Replacement(s,a,ai,d);generator=fixture.Generator()
            def stopped(g,job):
                fixture.Tests().writer(g,job);p=g.load_job(job)['payload'];p.pop('deep',None)
                p['reason']='독립 Fact 조사 보류';p['error_diagnostic']={'reason':'FACT_SEARCH_UNCITED','summary':p['reason']}
                g.save(job,'독립 Fact 조사','HOLD',p);return {'status':'HOLD'}
            with patch.object(Generation,'resume',autospec=True,side_effect=stopped) as resumed:
                out=svc.start(pid,TITLE,generator)
            self.assertEqual(resumed.call_count,1);self.assertEqual(ai.search_calls,[])
            self.assertFalse(out.get('replacement_preview_ready'));self.assertEqual(generator.calls,[])
            self.assertTrue(out['proposed_content']);s.close()

    def test_final_stage_reuses_bounded_recovery_and_binds_success_to_exact_article(self):
        for stage in ('최종 Fact 검색','수정안 최종 독립 Fact 검색'):
            with self.subTest(stage=stage):
                responses=iter([response('none'),response('cited')]);records=[]
                ai=Gemini('key','model',lambda p:next(responses))
                content='<h2>안전 점검</h2><p>설명서의 조건을 확인합니다.</p>'
                result=collect(ai,TITLE,content,pack(),record=records.append,stage=stage,image_generation_started=True)
                self.assertEqual(result['article_hash'],digest({'title':TITLE,'content':content}))
                self.assertEqual(len(records),2);self.assertEqual(len(result['citations']),2)

    def test_broken_and_duplicate_citations_are_not_counted_as_real_sources(self):
        source={'url':'https://manufacturer.example/manual'}
        self.assertEqual(valid_citations({'citations':[source,source,{'url':'http://example.com'},None,{'url':42}]}),[source])


    def test_search_only_error_metadata_is_reported_without_unrelated_empty_body_error(self):
        raw=response('error');raw['steps']=raw['steps'][:-1]
        result=Gemini('key','model',lambda p:raw).ask('query',search=True)
        self.assertEqual(result['text'],'');self.assertEqual(result['citations'],[])
        self.assertEqual(result['search_diagnostic']['execution'],'ERROR')
        self.assertEqual(result['search_diagnostic']['error_count'],1)
        with self.assertRaises(AIError):Gemini('key','model',lambda p:raw).ask('ordinary text')
        raw['steps'].append({'type':'model_output','content':[{'type':'text','text':None}]})
        with self.assertRaises(AIError) as caught:Gemini('key','model',lambda p:raw).ask('query',search=True)
        self.assertEqual(caught.exception.diagnostic['reason'],'INVALID_OUTPUT_BLOCK')

    def test_real_initial_generation_recovers_once_or_preserves_writer_body_without_recursive_search(self):
        from test_dev75_original_refill import AI as OriginalAI,QUOTE
        from r3studio.sources import SourceReader
        from r3studio.replacement import Replacement
        for kinds,success in [(['none','cited'],True),(['result','result'],False)]:
            with self.subTest(success=success),tempfile.TemporaryDirectory() as d:
                class InitialAI(OriginalAI):
                    def __init__(self):
                        super().__init__();self.responses=list(kinds);self.fact_calls=0
                        self.client=Gemini('key','gemini-3.8-flash',self.transport)
                    def transport(self,payload):return response(self.responses.pop(0))
                    def ask(self,prompt,*args,**kw):
                        if '완성 글의 핵심 사실' in prompt or 'R3 FACT SEARCH CITATION RECOVERY' in prompt:
                            self.fact_calls+=1;return self.client.ask(prompt,*args,**kw)
                        return super().ask(prompt,*args,**kw)
                s,a,pid=fixture.Tests().setup_case(d);ai=InitialAI();generator=fixture.Generator()
                reader=SourceReader(s,lambda url:{'status':200,'url':url,'headers':{'content-type':'text/html'},'body':'<p>'+QUOTE*8+'</p>'})
                with patch('r3studio.sources.SourceReader',return_value=reader):
                    svc=Replacement(s,a,ai,d);out=svc.start(pid,TITLE,generator)
                self.assertEqual(ai.fact_calls,2);self.assertEqual(len(ai.writers),1);self.assertTrue(out['proposed_content'])
                self.assertEqual(out['proposed_title'],TITLE);self.assertEqual(a.get_post('1')['content'],out['before']['content'])
                payload=Generation(s,ai,'blog').load_job(out['replacement_job_id'])['payload']
                self.assertTrue(payload['text_versions'])
                if success:
                    self.assertTrue(out.get('replacement_preview_ready'),out.get('reason'));self.assertEqual(len(generator.calls),2)
                else:
                    self.assertFalse(out.get('replacement_preview_ready'));self.assertEqual(generator.calls,[])
                    self.assertNotIn('deep',payload);self.assertNotIn('independent_fact_search',payload)
                    self.assertEqual(out['error_diagnostic']['reason'],'FACT_SEARCH_UNCITED')
                s.close()

if __name__=='__main__':unittest.main()
