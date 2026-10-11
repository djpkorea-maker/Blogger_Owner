"""Known unreadable source rows are structural data, never verified evidence."""
import copy,json,tempfile,unittest
from unittest.mock import patch,Mock
from r3studio.origin_response import shape_issues,request_review,contract_summary
from r3studio.sources import verify_origins,require_originals
from r3studio.evidence import EvidenceHold
from r3studio.presentation import diagnostic_lines
from r3studio.sync import now,digest
from r3studio.tasks import finish_validation
from r3studio.final_text_repair import repair
import test_dev84_final_text_repair as base

TEXTS=['합성 예제 제품의 점검 조건과 실제 설명서의 지침을 대조합니다. '+str(i) for i in range(4)]
def pack():
 return {'sources':[{'id':'s'+str(i+1),'url':'https://'+host+'/guide','grade':'A'}
                    for i,host in enumerate(('maker.example','agency.example','third.example','blocked.example'))],
         'facts':[{'id':'f'+str(i),'text':text,'source_ids':['s1' if i%2==0 else 's2'],
                   'core':i<2,'kind':['core','core','practical','condition'][i]} for i,text in enumerate(TEXTS)]}
class Reader:
 def read_many(self,sources,progress):
  text=' '.join(TEXTS)
  return {s['id']:{'status':'UNAVAILABLE' if s['id']=='s4' else 'FETCHED','text':text if s['id']!='s4' else '',
                   'text_hash':digest(text),'checked_at':now(),'final_url':s['url'],'reason':'합성 접근 실패' if s['id']=='s4' else ''}
          for s in sources}
def context():
 p=pack();originals=Reader().read_many(p['sources'],lambda *a:None)
 return {'facts':p['facts'],'sources':p['sources'],'originals':{sid:v for sid,v in originals.items() if v['status']=='FETCHED'}}
def answer(ctx=None):
 ctx=ctx or context()
 return {'sources':[{'source_id':s['id'],'grade':'UNKNOWN' if s['id']=='s4' else 'A','publisher':'' if s['id']=='s4' else s['id']} for s in ctx['sources']],
         'claims':[{'fact_id':f['id'],'source_id':f['source_ids'][0],'quote':f['text'],'supported':True} for f in ctx['facts']]}
class AI:
 def __init__(self,kind='known'):self.calls=0;self.kind=kind;self.prompts=[]
 def structured_object(self,prompt,schema):
  self.calls+=1;self.prompts.append(prompt)
  ctx=json.loads(prompt.split('\n',1)[1]);out=answer(ctx)
  if self.kind=='unknown' or self.kind=='repair' and self.calls==1:out['sources'][3]['source_id']='invented-private-value'
  if self.kind=='false':out['claims'][0]['supported']=False;out['claims'][0]['quote']=''
  if self.kind=='wrong_quote':out['claims'][0]['quote']='원문에서 확인하지 못한 내용을 만들어서 인용합니다.'
  if self.kind=='unreadable':
   out['sources'][3]['grade']='A';out['sources'][3]['publisher']='s4'
   out['claims'][0]['source_id']='s4'
  return out

class Tests(unittest.TestCase):
 def test_reported_sources_fourth_row_can_reference_known_unreadable_ledger_source(self):
  ctx=context();v=answer();self.assertIn('s4',{s['id'] for s in ctx['sources']});self.assertNotIn('s4',ctx['originals'])
  self.assertEqual(shape_issues(v,ctx),[])
  self.assertEqual(contract_summary(ctx,v),{'ledger_sources':4,'readable_originals':3,'unavailable_ledger_sources':1,'unavailable_response_rows':[4]})
 def test_unsupported_claim_bound_to_known_unreadable_source_is_not_json_failure(self):
  v=answer();v['claims'][0].update(source_id='s4',supported=False,quote='')
  self.assertEqual(shape_issues(v,context()),[])
 def test_known_unreadable_row_does_not_trigger_second_ai_call_or_change_input(self):
  ai=AI();ctx=context();before=copy.deepcopy(ctx)
  v,trace=request_review(ai,ctx)
  self.assertEqual(ai.calls,1);self.assertEqual(v,answer());self.assertEqual(ctx,before)
  self.assertEqual(trace[0]['state'],'VALID_SHAPE')
  self.assertEqual(trace[0]['source_contract']['unavailable_response_rows'],[4])
  data=json.loads(ai.prompts[0].split('\n',1)[1])
  self.assertEqual(data['source_id_contract']['unavailable_ledger_ids'],['s4'])
 def test_legacy_context_without_source_list_can_use_only_provided_original_ids(self):
  ctx=context();ctx.pop('sources');v=answer();v['sources']=v['sources'][:3]
  self.assertEqual(shape_issues(v,ctx),[])
  v['sources'].append({'source_id':'s4','grade':'UNKNOWN','publisher':''})
  self.assertTrue(shape_issues(v,ctx))
 def test_actual_unknown_source_remains_blocked_after_one_bounded_retry_and_visible_in_reason(self):
  ai=AI('unknown')
  with self.assertRaises(EvidenceHold) as caught:request_review(ai,context())
  self.assertEqual(ai.calls,2)
  detail=caught.exception.diagnostic
  self.assertEqual(detail['reason'],'ORIGINAL_REVIEW_FORMAT')
  self.assertIn('sources[4].source_id',str(caught.exception))
  self.assertIn('장부에도 없는 ID',str(caught.exception))
  text='\n'.join(diagnostic_lines(detail))
  self.assertIn('출처 ID 대조: 장부 4개 / 읽은 원문 3개 / 원문 미확보 1개',text)
  self.assertNotIn('invented-private-value',text)
 def test_unknown_claim_id_and_source_id_and_nonboolean_are_still_shape_failures(self):
  for field,value in [('fact_id','wrong'),('source_id','wrong'),('supported','false')]:
   v=answer();v['claims'][0][field]=value
   self.assertTrue(shape_issues(v,context()))
 def test_duplicate_known_unreadable_rows_are_not_ignored_as_harmless(self):
  v=answer();v['sources'].append(copy.deepcopy(v['sources'][3]))
  self.assertIn('중복 판정 행',' '.join(shape_issues(v,context())))
 def test_unknown_id_can_be_corrected_once_using_original_id_contract(self):
  ai=AI('repair');v,trace=request_review(ai,context())
  self.assertEqual(ai.calls,2)
  self.assertEqual([t['state'] for t in trace],['FORMAT_ERROR','VALID_SHAPE'])
  self.assertEqual(v,answer())
 def test_original_truth_still_requires_actual_quotes_and_never_counts_unreadable_source(self):
  ai=AI();p=verify_origins(ai,pack(),Reader());require_originals(p)
  self.assertEqual(ai.calls,1)
  verification=p['original_verification']
  self.assertNotIn('s4',verification['trusted_sources'])
  self.assertEqual(verification['source_independence']['trusted_sources'],3)
  source=next(s for s in verification['source_independence']['sources'] if s['source_id']=='s4')
  self.assertFalse(source['counted'])
  self.assertEqual(verification['response_format_attempts'][0]['source_contract']['unavailable_response_rows'],[4])
 def test_even_true_support_and_a_grade_for_unreadable_source_cannot_pass_core_claim(self):
  with self.assertRaises(EvidenceHold) as caught:verify_origins(AI('unreadable'),pack(),Reader())
  detail=caught.exception.diagnostic
  self.assertEqual(detail['reason'],'EVIDENCE_ORIGINALS_INCOMPLETE')
  self.assertTrue(detail['claims_evaluated']);self.assertEqual(detail['verification_counts']['supported_facts'],3)
  self.assertFalse(next(s for s in detail['source_independence']['sources'] if s['source_id']=='s4')['counted'])
  with self.assertRaises(EvidenceHold):require_originals(caught.exception.partial_pack)
 def test_false_support_or_fabricated_quote_still_holds(self):
  for kind in ('false','wrong_quote'):
   with self.subTest(kind=kind),self.assertRaises(EvidenceHold) as caught:
    verify_origins(AI(kind),pack(),Reader())
   self.assertEqual(caught.exception.diagnostic['failure_phase'],'CLAIM_SUPPORT')
   with self.assertRaises(EvidenceHold):require_originals(caught.exception.partial_pack)
 def test_source_contract_fix_does_not_relax_independent_publishers(self):
  p=pack();p['sources'][1]['url']='https://help.maker.example/guide';p['sources'][2]['url']='https://other.maker.example/guide'
  with self.assertRaises(EvidenceHold) as caught:verify_origins(AI(),p,Reader())
  self.assertEqual(caught.exception.diagnostic['failure_phase'],'SOURCE_INDEPENDENCE')
  self.assertFalse(caught.exception.diagnostic['claims_evaluated'])
 def test_final_validation_task_retains_specific_id_reason_and_pending_claims(self):
  ai=AI('unknown')
  with self.assertRaises(EvidenceHold) as caught:verify_origins(ai,pack(),Reader())
  error=caught.exception;task=Mock()
  finish_validation(task,{'status':'HOLD','reason':str(error),'error_diagnostic':error.diagnostic})
  detail=json.loads(task.finish.call_args.args[1])
  self.assertIn('sources[4].source_id',detail['summary'])
  self.assertFalse(detail['claims_evaluated']);self.assertEqual(detail['unverified_claims'],[])
  self.assertEqual([s['source_number'] for s in detail['source_checks']],[1,2,3,4])
 def test_real_final_validation_keeps_body_pixels_and_request_ids_through_source_contract_review(self):
  helpers=base.Tests()
  with tempfile.TemporaryDirectory() as d:
   store,server,service,pid,oldai,before=helpers.fixture(d)
   class UnreadableReader(base.Reader):
    def read_many(self,sources,progress):
     result=super().read_many(sources,progress)
     for sid in ('s3','s4'):result[sid].update(status='UNAVAILABLE',text='',reason='합성 접근 실패')
     return result
   class FinalAI(base.AI):
    def structured_object(self,prompt,schema):
     result=super().structured_object(prompt,schema)
     if not prompt.startswith('R3 FINAL EVIDENCE PARAGRAPH REPAIR:'):
      result['sources'] += [{'source_id':sid,'grade':'UNKNOWN','publisher':''} for sid in ('s3','s4')]
     return result
   p=base.ledger();p['sources'] += [{'id':'s3','url':'https://unreadable3.example/manual','grade':'A'},
                                  {'id':'s4','url':'https://unreadable4.example/manual','grade':'A'}]
   service.ai=FinalAI()
   with helpers.checks(service),patch('r3studio.evidence.Research.collect',return_value=p),patch('r3studio.sources.SourceReader',return_value=UnreadableReader()):
    result=service.validate(pid)
   self.assertEqual(result['status'],'PASS',result.get('reason'))
   self.assertEqual(result['proposed_content'],before['proposed_content'])
   for key in ('1','2'):
    self.assertEqual(result['image_choices'][key]['request_id'],before['image_choices'][key]['request_id'])
    self.assertEqual(result['image_choices'][key]['candidate']['info'],before['image_choices'][key]['candidate']['info'])
   self.assertEqual(len(server.uploads),2);require_originals(result['evidence']);store.close()
if __name__=='__main__':unittest.main()
