"""PSL source counting and pre-claim HOLD recovery, with synthetic claim fixtures."""
import copy,json,unittest
from unittest.mock import patch,Mock
from r3studio.source_domains import registered_domain,claims_not_evaluated
from r3studio.sources import verify_origins,require_originals
from r3studio.evidence import EvidenceHold
from r3studio.generation_recovery import coverage
from r3studio.presentation import diagnostic_lines
from r3studio.sync import digest,now
from r3studio.final_text_repair import repair
from tldextract import TLDExtract

# Real URL shapes reproduce the defect; these are not account/factual test data.
SAMSUNG='https://www.samsungsvc.co.kr/solution/147574'
LG='https://www.lge.co.kr/story/user-guide/thinq-discover-cleaning-047'
QUOTES=['합성 원문에서 모델별 점검 조건을 확인합니다. '+str(i) for i in range(5)]
def pack(urls=(SAMSUNG,LG)):
    return {'sources':[{'id':'s'+str(i+1),'url':url,'grade':'A'} for i,url in enumerate(urls)],
            'facts':[{'id':'f'+str(i),'text':text,'source_ids':['s'+str(i%2+1)],
                      'core':i<2,'kind':['core','core','practical','condition','other'][i]}
                     for i,text in enumerate(QUOTES)]}
class Reader:
    def __init__(self,status='FETCHED',final_urls=None):
        self.calls=0;self.status=status;self.final_urls=final_urls
    def read_many(self,sources,progress):
        self.calls+=1;text=' '.join(QUOTES)
        return {s['id']:{'status':self.status if i else 'FETCHED','text':text,
                         'text_hash':digest(text),'checked_at':now(),
                         'final_url':self.final_urls[i] if self.final_urls else s['url']}
                for i,s in enumerate(sources)}
class AI:
    def __init__(self,publishers=('Samsung','LG'),grades=('A','A'),bad_quote=False):
        self.publishers=publishers;self.grades=grades;self.bad_quote=bad_quote;self.calls=0
    def structured_object(self,prompt,schema):
        self.calls+=1;data=json.loads(prompt.split('\n',1)[1])
        return {'sources':[{'source_id':s['id'],'publisher':self.publishers[i],'grade':self.grades[i]}
                           for i,s in enumerate(data['sources'])],
                'claims':[{'fact_id':f['id'],'source_id':f['source_ids'][0],
                           'quote':'존재하지 않는 인용 구절을 만들어 냈습니다.' if self.bad_quote and i==0 else f['text'],
                           'supported':True} for i,f in enumerate(data['facts'])]}

class Tests(unittest.TestCase):
    def test_korean_publishers_are_distinct_in_live_saved_and_writer_checks(self):
        p=verify_origins(AI(),pack(),Reader())
        require_originals(p)
        v=p['original_verification']['source_independence']
        self.assertEqual(v['domains'],['lge.co.kr','samsungsvc.co.kr'])
        self.assertEqual(v['registered_domains'],2);self.assertEqual(v['publishers'],2)
        self.assertEqual(coverage(p)['coverage']['used_domains'],2)
        self.assertEqual(len(p['original_verification']['claims']),5)

    def test_country_suffixes_private_suffixes_wildcards_and_exceptions(self):
        cases={'https://www.samsungsvc.co.kr/':'samsungsvc.co.kr',
               'https://help.lge.co.kr/':'lge.co.kr',
               'https://news.bbc.co.uk/':'bbc.co.uk',
               'https://www.abc.net.au/':'abc.net.au',
               'https://www.example.com.au/':'example.com.au',
               'https://sub.one.blogspot.com/':'one.blogspot.com',
               'https://two.blogspot.com/':'two.blogspot.com',
               'https://a.one.github.io/':'one.github.io',
               'https://www.city.kawasaki.jp/':'city.kawasaki.jp',
               'https://a.b.ck/':'a.b.ck',
               'https://www.ck/':'www.ck',
               'https://bücher.de/':'xn--bcher-kva.de',
               'https://WWW.LGE.CO.KR.:443/':'lge.co.kr',
               'https://sub.maker.example/':'maker.example'}
        for url,expected in cases.items():
            with self.subTest(url=url):self.assertEqual(registered_domain(url),expected)

    def test_public_suffix_ip_credentials_and_malformed_urls_get_no_credit(self):
        for url in ('https://co.kr/','https://blogspot.com/','https://127.0.0.1/',
                    'https://[::1]/','https://localhost/','file:///local/path',
                    'https://user:pass@lge.co.kr/','https://lge.co.kr:bad/',
                    'https://a..lge.co.kr/','https://-a.lge.co.kr/','https://lge.co.kr /',
                    'https://[broken/','not-a-url',None):
            with self.subTest(url=url):self.assertEqual(registered_domain(url),'')

    def test_offline_psl_does_not_fetch_or_use_mutable_disk_cache(self):
        fresh=TLDExtract(suffix_list_urls=(),cache_dir=None,include_psl_private_domains=True)
        with patch('r3studio.source_domains._EXTRACT',fresh),patch('requests.sessions.Session.request',side_effect=AssertionError('network forbidden')):
            self.assertEqual(registered_domain(SAMSUNG),'samsungsvc.co.kr')
            self.assertEqual(registered_domain(LG),'lge.co.kr')

    def test_same_company_subdomains_and_paths_still_hold_before_claims(self):
        for urls in ((SAMSUNG,'https://help.samsungsvc.co.kr/video/218582'),
                     (SAMSUNG,'https://www.samsungsvc.co.kr/video/4602752')):
            with self.subTest(urls=urls),self.assertRaises(EvidenceHold) as caught:
                verify_origins(AI(),pack(urls),Reader())
            d=caught.exception.diagnostic
            self.assertEqual(d['failure_phase'],'SOURCE_INDEPENDENCE')
            self.assertFalse(d['claims_evaluated']);self.assertIsNone(d['verification_counts']['supported_facts'])
            self.assertEqual(d['verification_counts']['pending_facts'],5)
            self.assertEqual(d['unverified_claims'],[])
            self.assertTrue(all(c['state']=='NOT_EVALUATED' for c in d['claim_checks']))
            self.assertEqual(d['source_independence']['missing'],['등록 도메인'])
            lines='\n'.join(diagnostic_lines(d))
            self.assertIn('문장별 지원 판정: 미실시',lines)
            self.assertNotIn('원문 근거 판정: 장부',lines)
            self.assertNotIn('근거 미확보 주장:',lines)
            with self.assertRaises(EvidenceHold):require_originals(caught.exception.partial_pack)

    def test_actual_destination_controls_domain_count_after_redirect(self):
        reader=Reader(final_urls=[SAMSUNG,'https://other.samsungsvc.co.kr/'])
        with self.assertRaises(EvidenceHold):verify_origins(AI(),pack(),reader)

    def test_saved_claims_cannot_bypass_shared_domain_check(self):
        p=verify_origins(AI(),pack(),Reader())
        p['original_verification']['originals']['s2']['final_url']='https://help.samsungsvc.co.kr/'
        with self.assertRaises(EvidenceHold):require_originals(p)

    def test_same_publisher_or_unqualified_source_still_fails_distinct_domains(self):
        for ai,label in ((AI(publishers=('Samsung','Samsung')),'발행 주체'),
                         (AI(grades=('A','UNKNOWN')),'A/B 원문')):
            with self.subTest(label=label),self.assertRaises(EvidenceHold) as caught:
                verify_origins(ai,pack(),Reader())
            self.assertIn(label,caught.exception.diagnostic['source_independence']['missing'])

    def test_unavailable_source_is_not_reported_as_false_claims(self):
        with self.assertRaises(EvidenceHold) as caught:verify_origins(AI(),pack(),Reader('UNAVAILABLE'))
        d=caught.exception.diagnostic
        self.assertEqual(d['failure_phase'],'ORIGINAL_ACCESS');self.assertEqual(d['unverified_claims'],[])
        self.assertTrue(claims_not_evaluated(d));self.assertEqual(len(d['verification_targets']),5)

    def test_domain_fix_does_not_approve_false_quote_or_core_claim(self):
        with self.assertRaises(EvidenceHold) as caught:verify_origins(AI(bad_quote=True),pack(),Reader())
        d=caught.exception.diagnostic
        self.assertTrue(d['claims_evaluated']);self.assertEqual(d['failure_phase'],'CLAIM_SUPPORT')
        self.assertEqual(d['verification_counts']['supported_facts'],4)
        self.assertEqual(d['unverified_claims'][0]['text'],QUOTES[0])
        self.assertIn('인용 구절',d['unverified_claims'][0]['reason'])
        with self.assertRaises(EvidenceHold):require_originals(caught.exception.partial_pack)

    def test_preclaim_repair_revalidates_same_body_images_and_uploads_without_prose_edits(self):
        for d in ({'reason':'EVIDENCE_ORIGINALS_INCOMPLETE','summary':'확인된 독립 출처 2개 미만',
                   'unverified_claims':[{'text':q,'reason':'legacy'} for q in QUOTES]},
                  {'reason':'EVIDENCE_ORIGINALS_INCOMPLETE','claims_evaluated':False,
                   'failure_phase':'SOURCE_INDEPENDENCE'}):
            payload={'mode':'REPLACEMENT','replacement_preview_ready':True,
                     'proposed_title':'사용자가 선택한 제목','proposed_content':'<p>현재 본문</p>',
                     'before':{'title':'이전 제목'},'image_slots':[{'selected':'1'},{'selected':'2'}],
                     'uploaded_images':[{'uuid':'same-1'},{'uuid':'same-2'}],'error_diagnostic':d}
            before=copy.deepcopy(payload)
            service=Mock();service.load.return_value=(None,payload);service.validate.return_value={'status':'PASS'}
            with patch('r3studio.final_text_repair.paragraph_targets',side_effect=AssertionError('no prose edits')):
                result=repair(service,7)
            self.assertEqual(result,{'status':'PASS'});self.assertEqual(payload,before)
            service.validate.assert_called_once_with(7);service.save.assert_not_called()
            service.ai.structured_object.assert_not_called();service.ai.image_object.assert_not_called()

    def test_legacy_independence_hold_display_does_not_mislabel_unchecked_claims(self):
        old={'reason':'EVIDENCE_ORIGINALS_INCOMPLETE','summary':'확인된 독립 출처 2개 미만',
             'verification_counts':{'listed_facts':5,'supported_facts':0,'unverified_facts':5},
             'unverified_claims':[{'text':q,'reason':'미확보'} for q in QUOTES]}
        text='\n'.join(diagnostic_lines(old))
        self.assertIn('문장별 지원 판정: 미실시',text)
        self.assertNotIn('근거 미확보 주장:',text);self.assertNotIn('지원 확인 0개',text)
        self.assertIn(QUOTES[0],text)

    def test_packaged_build_carries_psl_snapshot_for_both_executables(self):
        import build_windows
        for cmd in build_windows.build_commands('python'):
            self.assertIn('--add-data',cmd)
            self.assertTrue(any('.tld_set_snapshot;tldextract' in arg for arg in cmd))

if __name__=='__main__':unittest.main()
