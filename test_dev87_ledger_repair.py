"""Reproduce classification-only HOLD, caption pollution and diagnostic repair."""
import copy,json,tempfile,unittest
from unittest.mock import patch
from r3studio.evidence import Research,EvidenceHold,ArticleContext,validate_pack,collect_cached
from r3studio.ledger_conditions import review,has_condition,role_hash
from r3studio.sources import require_originals,verify_origins
from r3studio.final_text_repair import paragraph_targets,apply_answer,repairable_diagnostic,signature
from r3studio.presentation import diagnostic_lines
from r3studio.sync import Store
import test_dev84_final_text_repair as base

FACTS=[
 '로봇청소기가 주행 중 문턱이나 장애물에 걸려 본체가 끼이거나 구동바퀴가 들리면 경고 알림(느낌표 아이콘 등)을 표시하며 동작을 멈출 수 있습니다.',
 '사용자가 직접 수동으로 청정스테이션이나 충전대 단자에 맞추어 올려 충전해 주어야 합니다.',
 '예를 들어 똑같은 1cm 높이의 문턱이라도 완만한 계단형 구조는 수월하게 넘어가지만, 직각 형태의 일자형 문턱은 전면 범퍼나 센서가 장애물로 인식하여 통과를 시도하지 못하고 멈출 수 있습니다.',
 '마그네틱 센서를 지원하는 기기라면 물리적인 진입 방지 테이프를 바닥에 부착해 통과를 차단할 수 있으며, 라이다 센서 기반의 최신 스마트 모델이라면 전용 모바일 앱의 맵 관리 화면에서 가상 벽이나 청소 금지 구역을 설정하여 로봇청소기가 해당 문턱 구역으로 접근하지 않도록 사전에 예방 조치를 취하는 것이 안전합니다.'
]
BAD='동일한 턱에서 두 번 이상 헛도는 상태를 무리하게 반복시키면 구동 모터 과열이나 하부 주행계 부품 손상으로 이어질 수 있으므로 주행 시도를 즉시 중단해야 합니다.'
CAP='그림 1. 검은색 원형 로봇청소기가 나무 문턱에 걸려 비스듬하게 멈춰 있습니다.'
FIG='<figure><img src="https://lh3.googleusercontent.com/a" alt="보존 ALT"><figcaption>'+CAP+'</figcaption></figure>'
def ledger():
 return {'sources':[{'id':'a','url':'https://manufacturer.example/manual','grade':'A'},{'id':'b','url':'https://agency.example/guide','grade':'A'}],
         'facts':[{'id':str(i),'text':v,'article_excerpt':v,'source_ids':['a' if i%2==0 else 'b'],
                   'core':i<3,'kind':['core','practical','core','practical'][i]} for i,v in enumerate(FACTS)]}
class AI:
 model='fixture87'
 def __init__(self,conditions=None,bad=False):
  self.conditions=[{'fact_id':'2','excerpt':FACTS[2]}] if conditions is None else conditions
  self.roles=0;self.searches=0;self.ledgers=0;self.bad=bad
 def ask(self,prompt,**kw):
  self.searches+=1;return {'citations':[{'url':s['url']} for s in ledger()['sources']]}
 def object(self,prompt):
  if prompt.startswith('R3 LEDGER CONDITION ROLE:'):
   self.roles+=1;return {'conditions':copy.deepcopy(self.conditions)}
  self.ledgers+=1;p=ledger()
  if self.bad:p['claim_checks']=[{'text':BAD,'status':'UNVERIFIED','reason':'임의 횟수와 고장 결과의 직접 근거 없음'}]
  return p
class Tests(unittest.TestCase):
 def test_reported_four_facts_three_core_can_have_secondary_condition_without_new_facts(self):
  p=ledger();before=copy.deepcopy(p)
  with self.assertRaisesRegex(EvidenceHold,'조건·예외'):validate_pack(p)
  fixed,event=review(AI(),p,' '.join(FACTS))
  validate_pack(fixed)
  self.assertEqual(len(fixed['facts']),4)
  self.assertEqual(sum(f['core'] for f in fixed['facts']),3)
  for old,new in zip(before['facts'],fixed['facts']):
   self.assertEqual(old,{k:v for k,v in new.items() if k!='condition_role'})
  self.assertFalse(event['truth_verified'])
  with self.assertRaises(EvidenceHold):require_originals(fixed)
 def test_condition_review_occurs_once_before_another_search(self):
  ai=AI();p=Research(ai).collect('t','t',article='<p>'+' '.join(FACTS)+'</p>')
  self.assertEqual((ai.searches,ai.ledgers,ai.roles),(1,1,1));self.assertTrue(has_condition(p['facts'][2]))
  self.assertNotIn('original_verification',p)
 def test_no_actual_condition_still_holds_after_bounded_role_review(self):
  ai=AI(conditions=[])
  with self.assertRaises(EvidenceHold) as caught:Research(ai).collect('t','t',article='<p>'+' '.join(FACTS)+'</p>')
  self.assertEqual(ai.roles,1);self.assertEqual((ai.searches,ai.ledgers),(3,5))
  self.assertTrue(caught.exception.diagnostic['recovery_exhausted'])
  with self.assertRaises(EvidenceHold):require_originals(caught.exception.partial_pack)
 def test_unknown_id_fabricated_excerpt_duplicate_and_short_role_are_rejected(self):
  for items in ([{'fact_id':'new','excerpt':FACTS[2]}],
                [{'fact_id':'2','excerpt':'이 모델은 실제로 다른 높이의 문턱을 통과합니다.'}],
                [{'fact_id':'2','excerpt':FACTS[2]}]*2,[{'fact_id':'2','excerpt':'1cm'}]):
   with self.subTest(items=items),self.assertRaises(EvidenceHold):review(AI(items),ledger())
 def test_changed_fact_invalidates_its_secondary_role(self):
  p,_=review(AI(),ledger());f=p['facts'][2];self.assertTrue(has_condition(f))
  f['text']+=' 새 문장';self.assertFalse(has_condition(f))
 def test_classification_cannot_bypass_real_original_truth_or_independence(self):
  p,_=review(AI(),ledger())
  class Refuse:
   def object(self,prompt):
    return {'sources':[{'source_id':s['id'],'grade':'A','publisher':s['id']} for s in p['sources']],
            'claims':[{'fact_id':f['id'],'source_id':f['source_ids'][0],'quote':'','supported':False} for f in p['facts']]}
  class Reader:
   def read_many(self,sources,progress):
    from r3studio.sync import digest,now
    text=' '.join(FACTS)
    return {s['id']:{'status':'FETCHED','text':text,'text_hash':digest(text),'checked_at':now(),'final_url':s['url']} for s in sources}
  with self.assertRaises(EvidenceHold) as caught:verify_origins(Refuse(),p,Reader())
  self.assertTrue(caught.exception.diagnostic['claims_evaluated'])
  self.assertEqual(caught.exception.diagnostic['verification_counts']['supported_facts'],0)
 def test_search_flagged_nonledger_paragraph_cannot_silently_pass_research(self):
  ai=AI(bad=True)
  with self.assertRaises(EvidenceHold) as caught:
   Research(ai).collect('t','t',article='<p>'+' '.join(FACTS)+'</p><p>'+BAD+'</p>')
  error=caught.exception
  self.assertTrue(error.diagnostic['research_claims_only'])
  self.assertIn(BAD,str(error.diagnostic['unverified_claims']))
  self.assertTrue(repairable_diagnostic(error.diagnostic))
  with self.assertRaises(EvidenceHold):require_originals(error.partial_pack)
 def test_partial_research_draft_fetches_originals_for_diagnosis_but_is_not_cached(self):
  ai=AI(bad=True)
  with tempfile.TemporaryDirectory() as d:
   store=Store(d+'/db')
   with patch('r3studio.sources.SourceReader',return_value=base.Reader()):
    p=collect_cached(store,ai,'t','t','scope',article='<p>'+' '.join(FACTS)+'</p><p>'+BAD+'</p>',allow_partial=True)
   self.assertTrue(p['evidence_review']['diagnostic_only'])
   self.assertEqual(set(p['evidence_review']['originals']),{'a','b'})
   self.assertEqual(store.db.execute('SELECT COUNT(*) FROM evidence_packs').fetchone()[0],0)
   with self.assertRaises(EvidenceHold):require_originals(p)
   store.close()
 def test_article_context_excludes_figures_captions_references_but_keeps_faq_query(self):
  c='<h2>점검</h2><p>'+BAD+'</p>'+FIG+'<h2>참고 자료</h2><p>근거 자료 9</p>'
  result=ArticleContext(c).context()
  self.assertIn(BAD,result['article_text']);self.assertNotIn(CAP,result['article_text']);self.assertNotIn('근거 자료 9',result['article_text'])
  self.assertEqual(ArticleContext('<a href="https://help.example/faq?id=42">점검</a>').context()['existing_urls'],['https://help.example/faq?id=42'])
 def test_legacy_caption_tail_is_excluded_only_when_it_matches_actual_figure(self):
  c='<p>'+BAD+'</p>'+FIG
  blocks=paragraph_targets(c,{'unverified_claims':[{'text':BAD+CAP,'reason':'임의 횟수'}]})
  self.assertEqual(len(blocks),1);self.assertEqual(blocks[0]['claims'][0]['text'],BAD)
  self.assertEqual(blocks[0]['claims'][0]['excluded_caption'],CAP)
  with self.assertRaises(EvidenceHold):
   paragraph_targets(c,{'unverified_claims':[{'text':BAD+'그림 1. 현재 그림과 다른 설명입니다.'}]})
  with self.assertRaises(EvidenceHold):paragraph_targets(c,{'unverified_claims':[{'text':CAP}]})
 def test_multi_paragraph_diagnostic_targets_only_actual_prose_and_preserves_figure(self):
  first='본체를 옮긴 후에는 새로운 위치에서 별도 구역 청소를 시작합니다.'
  c='<p>보존할 정상 설명이 충분하게 있습니다. '+('다른 점검 내용입니다. '*100)+'</p><p>'+first+'</p><p>'+BAD+'</p>'+FIG
  b=paragraph_targets(c,{'unverified_claims':[{'text':first+' '+BAD+CAP,'reason':'직접 근거 없음'}]})
  self.assertEqual(len(b),2)
  result,_=apply_answer(c,b,{'edits':[{'block_id':x['block_id'],'new_html':'<p>'+base.GOOD[i]+'</p>','reason':'예제 원문 지침으로 한정'} for i,x in enumerate(b)]})
  self.assertIn(FIG,result);self.assertNotIn(BAD,result)
 def test_search_findings_display_even_before_original_claim_review(self):
  detail={'reason':'EVIDENCE_INCOMPLETE','claims_evaluated':False,'research_claims_only':True,
          'unverified_claims':[{'text':BAD,'reason':'검색 진단'}],
          'ledger':{'state':'COVERAGE','linked_facts':4,'core_facts':3,'condition_facts':0,'practical_facts':2}}
  text='\n'.join(diagnostic_lines(detail))
  self.assertIn('조건·예외 0개',text);self.assertIn('검색 단계 근거 연결 미확보 문장: '+BAD,text)
 def test_research_format_network_and_unknown_holds_do_not_expose_prose_repair(self):
  for d in ({'reason':'TIMEOUT'},{'reason':'EVIDENCE_INCOMPLETE','ledger':{'state':'FORMAT'}},
            {'reason':'EVIDENCE_INCOMPLETE','ledger':{'state':'COVERAGE'},'missing_criteria':'출처 URL 불일치'},
            {'reason':'EVIDENCE_INCOMPLETE','ledger':{'state':'COVERAGE'},'research_claims_only':True,'stage':'근거 조사','missing_criteria':'검색 결과 밖의 출처 URL 불일치'}):
   self.assertFalse(repairable_diagnostic(d))
 def test_reported_research_hold_repair_preserves_upload_receipts_and_then_strictly_validates(self):
  helpers=base.Tests()
  with tempfile.TemporaryDirectory() as d:
   store,server,service,pid,ai,before=helpers.fixture(d)
   _,p=service.load(pid)
   p['error_diagnostic']={'reason':'EVIDENCE_INCOMPLETE','missing_criteria':'조건·예외 근거 부족',
      'ledger':{'state':'COVERAGE'},'research_claims_only':True,'claims_evaluated':False,
      'unverified_claims':[{'text':base.BAD[0]+'그림 1. 첫 번째 장면을 보여 주는 설명입니다.','reason':'검색 연결 미확보'}]}
   service.save(pid,p)
   with helpers.checks(service):result=service.repair_evidence(pid)
   self.assertEqual(result['status'],'PASS',result.get('reason'))
   self.assertEqual(ai.repairs,1);self.assertEqual(ai.images,2)
   self.assertEqual(result['before'],before['before'])
   for key in ('1','2'):
    self.assertEqual(result['image_choices'][key]['request_id'],before['image_choices'][key]['request_id'])
    self.assertEqual(result['image_choices'][key]['candidate']['info'],before['image_choices'][key]['candidate']['info'])
   require_originals(result['evidence'])
   self.assertEqual(len(server.uploads),2)
   store.close()
 def test_research_hold_resumes_repair_instead_of_regenerating_accepted_images(self):
  from r3studio.replacement import Replacement
  helpers=base.Tests()
  with tempfile.TemporaryDirectory() as d:
   store,server,service,pid,ai,before=helpers.fixture(d)
   _,p=service.load(pid);p['error_diagnostic']={'reason':'EVIDENCE_INCOMPLETE','missing_criteria':'조건·예외 근거 부족','ledger':{'state':'COVERAGE'}}
   service.save(pid,p);replacement=Replacement(store,service.adapter,ai,d)
   with patch.object(replacement.images,'repair_evidence',return_value={'route':'repair'}) as repair:
    self.assertEqual(replacement.resume(pid,None),{'route':'repair'})
   repair.assert_called_once_with(pid);store.close()
if __name__=='__main__':unittest.main()
