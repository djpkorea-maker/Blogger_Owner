import io,json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
import test_dev68_repair_images as fixture
from test_generation import pack
from test_images import Vision
from r3studio.replacement import Replacement,replacement_target,text_ready,saved_replacements
from r3studio.repair_images import RepairImages
from r3studio.generation import Generation
from r3studio.images import ImageHold,inspect_bytes
from r3studio.sync import Sync,Store,digest,post_hash
from r3studio.publish import prepare,PublishHold
from r3studio.apply import Apply
from r3studio.cache_policy import force_whole_review,remember_checkpoint
from r3studio.gates import Document,run_checks
import test_apply_layout as apply_fixture

REVIEW={'fact':'PASS','safety':'PASS','intent':'PASS','practical_value':'PASS','originality':'PASS','score':95,'severity':'none','issues':[],'unsupported_claims':[]}
CONTENT='<h2>청소기 점검</h2><p>'+''.join('청소기 바퀴와 바닥 상태를 안전하게 확인하는 점검 항목 '+str(i)+'. ' for i in range(80))+'</p><h2>사용 조건</h2><p>제품 설명서를 확인합니다.</p>'
class AI(Vision):
 def object(self,p):
  if 'prompts:' in p:return {'prompts':['바퀴 확인 장면','바닥 정리 장면']}
  if 'ids:' in p:return {'ids':['2']}
  return dict(REVIEW)
 def ask(self,*a,**kw):return {'citations':[{'url':'https://manufacturer.example/manual'}]}
class Generator:
 model='fake-image'
 def __init__(self):self.calls=[]
 def image(self,prompt):
  self.calls.append(prompt);b=io.BytesIO();Image.new('RGB',(1024,576),'red' if len(self.calls)%2 else 'blue').save(b,format='PNG');return b.getvalue()
class Tests(unittest.TestCase):
 def setup_case(self,d):
  s,a,pid,c=fixture.Tests().setup_case(d,'HOLD')
  before=a.get_post('1');peer=dict(before,id='2',title='청소기 바퀴 관리',url='https://blog.example/peer')
  a.list_metadata=lambda:[{k:v[k] for k in ('id','status','updated','title','url')} for v in (before,peer)]
  a.get_post=lambda pid:dict(before if pid=='1' else peer)
  Sync(s,a,'blog').run()
  return s,a,pid
 def writer(self,g,job):
  p=g.load_job(job)['payload'];p.update(title='청소기 바퀴 점검 방법',content=CONTENT,search_description='청소기가 멈출 때 안전하게 점검하는 순서를 설명합니다.',evidence=pack(),fast={'issues':['이미지 2장 미만','내부링크 확인 필요']},deep={'review':dict(REVIEW),'text_verified':False})
  g.save(job,'이미지 대기','HOLD',p);return {'job_id':job,'status':'HOLD'}
 def start(self,s,a,pid,d):
  svc=Replacement(s,a,AI(),d)
  with patch.object(Generation,'resume',autospec=True,side_effect=self.writer):result=svc.start(pid,'청소기의 안전한 점검 방법',Generator())
  return svc,result
 def test_generation_builds_two_local_images_without_post_write_or_upload(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);svc,r=self.start(s,a,pid,d)
   self.assertNotEqual(r['proposal_id'],pid);self.assertEqual(r['status'],'HOLD');self.assertEqual(r['before']['id'],'1')
   self.assertEqual(r['before']['content'],a.get_post('1')['content']);self.assertEqual(len(Document(r['proposed_content']).images),2)
   self.assertEqual(set(r['image_choices']),{'1','2'});self.assertTrue(all(Path(c['file']).is_file() for c in r['image_edit_candidates'].values()))
   self.assertNotEqual(r['image_edit_candidates']['1']['info']['pixel_hash'],r['image_edit_candidates']['2']['info']['pixel_hash'])
   self.assertIn('https://blog.example/peer',r['proposed_content']);self.assertIn('r3-local:',r['proposed_content']);self.assertNotIn('plan',r)
   self.assertNotEqual(r['proposed_title'],r['before']['title']);s.close()
 def test_replacement_job_cannot_create_separate_blogger_post(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);svc,r=self.start(s,a,pid,d)
   with self.assertRaisesRegex(PublishHold,'전체 교체'):prepare(Generation(s,AI(),'blog'),r['replacement_job_id'])
   s.close()
 def test_text_failure_keeps_proposal_and_blocks_image_cost(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);gen=Generator()
   with patch.object(Generation,'resume',return_value={'status':'HOLD'}):r=Replacement(s,a,AI(),d).start(pid,'근거가 부족한 새 주제',gen)
   self.assertEqual(r['status'],'HOLD');self.assertEqual(gen.calls,[]);self.assertIn('replacement_job_id',r);s.close()
 def test_cancelled_image_blocks_final_validation_before_any_upload(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);svc,r=self.start(s,a,pid,d)
   svc.images.operate(r['proposal_id'],'cancel',2)
   r=svc.images.validate(r['proposal_id']);self.assertEqual(r['status'],'HOLD');self.assertIn('2장',r['reason']);self.assertNotIn('plan',r);s.close()
 def test_resume_preserves_job_number_and_does_not_repeat_good_images(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);svc,r=self.start(s,a,pid,d);gen=Generator()
   again=svc.resume(r['proposal_id'],gen)
   self.assertEqual(r['replacement_job_id'],again['replacement_job_id']);self.assertEqual(gen.calls,[]);self.assertEqual(s.db.execute('SELECT count(*) FROM generation_jobs').fetchone()[0],1);s.close()
 def test_changed_original_blocks_resume(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);svc,r=self.start(s,a,pid,d);original=a.get_post('1');a.get_post=lambda pid:dict(original,title='다른 사람이 편집한 제목')
   with self.assertRaisesRegex(ImageHold,'변경'):svc.resume(r['proposal_id'],Generator())
   s.close()
 def test_same_pixels_in_generated_slots_hold_second_image(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d)
   class Same(Generator):
    def image(self,prompt):return Generator().image(prompt)
   svc=Replacement(s,a,AI(),d)
   with patch.object(Generation,'resume',autospec=True,side_effect=self.writer):r=svc.start(pid,'다른 장면 생성 시험',Same())
   self.assertEqual(r['image_edit_candidates']['2']['result'],'HOLD');self.assertNotIn('2',r['image_choices']);s.close()
 def test_binding_to_other_proposal_is_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);svc,r=self.start(s,a,pid,d);g=Generation(s,AI(),'blog');p=g.load_job(r['replacement_job_id'])['payload'];p['replacement_target']['proposal_id']=pid
   with self.assertRaises(ImageHold):replacement_target(s,'blog',p)
   s.close()
 def test_title_change_is_used_in_strict_evidence_and_deep_gates(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);svc,r=self.start(s,a,pid,d);a.upload_image=lambda data,mime,name,rid:{'ok':True,'publicImageUrl':'https://lh3.googleusercontent.com/'+rid,'byte_hash':inspect_bytes(data)['byte_hash']}
   checked=[]
   def public_check(store,ai,title,content,*args):
    checked.append(title);return [{'result':'PASS','url':im['src'],'alt':im['alt'],'article_hash':digest({'title':title,'content':content})} for im in Document(content).images]
   with patch('r3studio.repair_images.collect_cached',return_value=pack()) as collect,patch('r3studio.repair_images.evaluate',return_value={'text_verified':True}) as deep,patch('r3studio.repair_images.check_public_images',side_effect=public_check),patch('r3studio.finalize.decide',return_value={'grade':'PASS'}) as final,patch('r3studio.repair_images.check_links',return_value={'pass':True}):
    result=svc.images.validate(r['proposal_id'])
   self.assertEqual(result['status'],'PASS',result.get('reason'));self.assertEqual(result['plan']['post_id'],'1');self.assertEqual(result['plan']['proposal']['title'],r['proposed_title']);self.assertNotIn('r3-local:',result['plan']['proposal']['content'])
   self.assertEqual(collect.call_args.args[2],r['proposed_title']);self.assertEqual(deep.call_args.args[1]['title'],r['proposed_title']);self.assertEqual(checked,[r['proposed_title']]);self.assertEqual(final.call_count,1);s.close()
 def test_start_from_post_does_not_require_a_prior_ai_repair(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);svc=Replacement(s,a,AI(),d)
   with patch.object(Generation,'resume',autospec=True,side_effect=self.writer):r=svc.start_post('1','처음부터 안전한 점검 안내',Generator())
   self.assertEqual(r['before']['id'],'1');self.assertEqual(set(r['image_choices']),{'1','2'});s.close()
 def test_apply_keeps_existing_post_id_url_state_and_schedule(self):
  for state in ('LIVE','DRAFT','SCHEDULED'):
   with self.subTest(state=state):
    s=Store(':memory:');a=apply_fixture.Adapter();a.post.update(status=state,published='2026-10-11T10:00:00Z');url=a.post['url']
    result=Apply(s,a).apply(Apply(s,a).prepare('1','새 제목',CONTENT))
    self.assertEqual(result['post_id'],'1');self.assertEqual(a.post['url'],url);self.assertEqual(a.post['status'],state);self.assertEqual(a.post['published'],'2026-10-11T10:00:00Z');self.assertEqual(a.writes,1);s.close()
 def test_server_schedule_change_is_unconfirmed_and_never_replayed(self):
  s=Store(':memory:')
  class Changed(apply_fixture.Adapter):
   def apply_update(self,plan):
    reply=super().apply_update(plan);self.post['published']='2026-10-12T10:00:00Z';return reply
  a=Changed();a.post.update(status='SCHEDULED',published='2026-10-11T10:00:00Z')
  with self.assertRaisesRegex(ValueError,'결과 불일치'):Apply(s,a).apply(Apply(s,a).prepare('1','새 제목',CONTENT))
  self.assertEqual(a.writes,1);self.assertEqual(s.db.execute('SELECT status FROM apply_history').fetchone()[0],'NEEDS_RECONCILE')
  a.request_status=lambda rid:{'status':'DONE','action':'apply_update','result':{'blogId':'blog','postId':'1','verified':True,'backupFileId':'backup','afterHash':post_hash(a.post)}}
  with self.assertRaises(ValueError):Apply(s,a).reconcile(1)
  self.assertEqual(a.writes,1);s.close()
 def test_post_schedule_change_blocks_patch(self):
  s=Store(':memory:');a=apply_fixture.Adapter();a.post.update(status='SCHEDULED',published='2026-10-11T10:00:00Z')
  svc=Apply(s,a);p=svc.prepare('1','새 제목',CONTENT);a.post['published']='2026-10-12T10:00:00Z'
  with self.assertRaisesRegex(ValueError,'예약'):svc.apply(p)
  self.assertEqual(a.writes,0);s.close()
 def test_dev70_checkpoint_can_be_reused_after_restart_in_dev71(self):
  from test_sync import Adapter
  with tempfile.TemporaryDirectory() as d:
   path=d+'/db';s=Store(path);a=Adapter();sync=Sync(s,a,'blog',force_refresh=force_whole_review(70)).run();checks=run_checks(s,'blog',True);
   with patch('r3studio.cache_policy.VERSION',70):remember_checkpoint(s,'blog',sync,checks)
   s.close()
   s=Store(path);self.assertEqual(s.db.execute('SELECT version FROM application_checkpoints').fetchone()[0],70)
   sync=Sync(s,a,'blog',force_refresh=force_whole_review(71)).run();checks=run_checks(s,'blog',force_whole_review(71))
   self.assertEqual(sync['reused'],3);self.assertEqual(checks['reused'],3);self.assertTrue(force_whole_review(71,True));s.close()
 def test_replacement_duplicate_search_excludes_target_but_keeps_other_posts(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);svc,r=self.start(s,a,pid,d);prompts=[]
   class Reject(AI):
    def object(self,prompt):prompts.append(prompt);return {'duplicate':True,'reason':'peer overlap'}
   g=Generation(s,Reject(),'blog');g.resume(r['replacement_job_id'])
   data=json.loads(prompts[0].split('\n',1)[1]);self.assertEqual([p['id'] for p in data['existing']],['2']);s.close()
 def test_saved_replacement_reload_is_blog_scoped_and_keeps_job_and_pixels(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);svc,r=self.start(s,a,pid,d)
   saved=saved_replacements(s,'blog');self.assertEqual(len(saved),1);self.assertEqual(saved[0]['replacement_job_id'],r['replacement_job_id']);self.assertEqual(saved[0]['image_choices'],r['image_choices']);self.assertEqual(saved_replacements(s,'another-blog'),[]);s.close()
 def test_resume_keeps_upload_request_and_manual_image_selection(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid=self.setup_case(d);svc,r=self.start(s,a,pid,d)
   _,p=svc.images.load(r['proposal_id']);p['image_choices']['1']['request_id']='sent-once';p['image_choices']['1']['receipt']={'ok':True};svc.images.save(r['proposal_id'],p)
   again=svc.resume(r['proposal_id'],Generator());self.assertEqual(again['image_choices']['1']['request_id'],'sent-once');self.assertEqual(again['image_choices']['1']['receipt'],{'ok':True});s.close()
 def test_text_ready_does_not_ignore_html_or_factual_failures(self):
  p={'deep':{'review':dict(REVIEW)},'fast':{'issues':['이미지 2장 미만']}};self.assertTrue(text_ready(p))
  p['fast']['issues'].append('태그 순서 확인: p');self.assertFalse(text_ready(p))
  p['fast']['issues']=[];p['deep']['review']['fact']='UNKNOWN';self.assertFalse(text_ready(p))

