import base64
import io
import json
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from PIL import Image
from r3studio.sync import Store,now,digest
from r3studio.generation import Generation
from r3studio.publish import prepare,Publisher,PublishHold
from r3studio.imagegen import Generator
from r3studio.ai import AIError
class Adapter:
 blog_id='blog'
 def __init__(self):self.post=None;self.inserts=0;self.publishes=0;self.fail=False
 def create_draft(self,p):
  self.inserts+=1
  if self.fail:raise TimeoutError()
  self.post={'id':'1','title':p['title'],'content':p['content'],'labels':p['labels'],'status':'DRAFT','updated':now(),'url':'https://blog.example/p'};return {'postId':'1'}
 def get_post(self,pid):return dict(self.post)
 def list_metadata(self):return [{k:self.post[k] for k in ('id','status','updated')}] if self.post else []
 def publish_post(self,post,p):
  self.publishes+=1;self.post.update(status=p['mode'],published=p['schedule'] or now(),updated=now())
class AI:model='test'
class Tests(unittest.TestCase):
 def test_damaged_pass_payload_blocks_plan_without_changes(self):
  for key,value in [('final',[]),('title',None),('composed_content',''),('labels','wrong'),('search_description',None)]:
   with self.subTest(key=key),tempfile.TemporaryDirectory() as d:
    s,g,j=self.generation(d+'/db');p=g.load_job(j)['payload'];p[key]=value;g.save(j,'검사 기록','PASS',p)
    with self.assertRaises(PublishHold):prepare(g,j)
    self.assertEqual(s.db.execute('SELECT status FROM generation_jobs').fetchone()[0],'PASS');s.close()
 def test_corrupt_job_json_is_controlled_hold(self):
  for raw in ('broken','[]','null'):
   with self.subTest(raw=raw),tempfile.TemporaryDirectory() as d:
    s,g,j=self.generation(d+'/db');s.db.execute('UPDATE generation_jobs SET payload=? WHERE id=?',(raw,j));s.db.commit()
    with self.assertRaises(PublishHold):prepare(g,j)
    self.assertEqual(s.db.execute('SELECT payload FROM generation_jobs').fetchone()[0],raw);s.close()
 def test_malformed_plans_block_before_any_remote_access(self):
  class NoRemote(Adapter):
   def get_post(self,pid):raise AssertionError('remote GET not allowed')
   def create_draft(self,p):raise AssertionError('remote write not allowed')
  with tempfile.TemporaryDirectory() as d:
   s,g,j=self.generation(d+'/db');valid=prepare(g,j);a=NoRemote();pub=Publisher(g,a)
   variants=[None,[],{}]
   for key,value in [('job_id',True),('labels','bad'),('schedule','2026-10-10'),('article_hash','wrong')]:
    damaged=dict(valid);damaged[key]=value;damaged['plan_hash']=digest({k:v for k,v in damaged.items() if k!='plan_hash'});variants.append(damaged)
   for damaged in variants:
    with self.subTest(plan=damaged),self.assertRaises(PublishHold):pub.execute(damaged)
   self.assertIsNone(s.db.execute("SELECT name FROM sqlite_master WHERE name='publish_history'").fetchone());s.close()
 def test_invalid_remote_schedule_remains_unconfirmed_without_retry(self):
  for actual in (None,'bad-date','2026-10-11T10:00:00'):
   class Bad(Adapter):
    def publish_post(self,post,p):super().publish_post(post,p);self.post['published']=actual
   with self.subTest(actual=actual),tempfile.TemporaryDirectory() as d:
    s,g,j=self.generation(d+'/db');a=Bad();pub=Publisher(g,a)
    when=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
    plan=prepare(g,j,'SCHEDULED',when)
    with self.assertRaises(PublishHold):pub.execute(plan)
    self.assertEqual(s.db.execute('SELECT status FROM publish_history').fetchone()[0],'NEEDS_RECONCILE')
    with self.assertRaises(PublishHold):pub.execute(plan)
    self.assertEqual(a.inserts,1);self.assertEqual(a.publishes,1);s.close()
 def test_schedule_comparison_handles_timezone_equivalence(self):
  from r3studio.publish import schedule_matches
  self.assertTrue(schedule_matches('2026-10-11T09:00:00+09:00','2026-10-11T00:00:00Z'))
  self.assertFalse(schedule_matches('2026-10-11T09:01:00+09:00','2026-10-11T00:00:00Z'))
 def test_corrupt_verified_history_blocks_all_followup_writes(self):
  for raw in ('not-json','[]','{}'):
   with self.subTest(raw=raw),tempfile.TemporaryDirectory() as d:
    s,g,j=self.generation(d+'/db');a=Adapter();pub=Publisher(g,a);pub.execute(prepare(g,j))
    s.db.execute('UPDATE publish_history SET payload=?',(raw,));s.db.commit()
    with self.assertRaises(PublishHold):pub.reconcile(j)
    with self.assertRaises(PublishHold):prepare(g,j)
    self.assertEqual(a.inserts,1);self.assertEqual(a.publishes,0);s.close()
 def test_tampered_history_plan_blocks_reconciliation(self):
  with tempfile.TemporaryDirectory() as d:
   s,g,j=self.generation(d+'/db');a=Adapter();pub=Publisher(g,a);pub.execute(prepare(g,j))
   saved=json.loads(s.db.execute('SELECT payload FROM publish_history').fetchone()[0])
   saved['plan']['title']='손상된 제목'
   s.db.execute('UPDATE publish_history SET payload=?',(json.dumps(saved),));s.db.commit()
   with self.assertRaises(PublishHold):pub.reconcile(j)
   self.assertEqual(a.inserts,1);self.assertEqual(a.publishes,0);s.close()
 def test_changed_mode_cannot_reuse_reviewed_plan(self):
  with tempfile.TemporaryDirectory() as d:
   s,g,j=self.generation(d+'/db');a=Adapter();plan=prepare(g,j);plan['mode']='LIVE'
   with self.assertRaises(PublishHold):Publisher(g,a).execute(plan)
   self.assertEqual(a.inserts,0);self.assertEqual(a.publishes,0);s.close()
 def test_verified_history_confirmation_checks_current_post(self):
  with tempfile.TemporaryDirectory() as d:
   s,g,j=self.generation(d+'/db');a=Adapter();pub=Publisher(g,a);pub.execute(prepare(g,j));a.post['content']='후속 수정'
   with self.assertRaises(PublishHold):pub.reconcile(j)
   self.assertEqual(a.inserts,1);s.close()
 def test_wrong_blog_is_blocked_before_insert(self):
  with tempfile.TemporaryDirectory() as d:
   s,g,j=self.generation(d+'/db');a=Adapter();a.blog_id='different'
   with self.assertRaises(PublishHold):Publisher(g,a).execute(prepare(g,j))
   self.assertEqual(a.inserts,0);s.close()
 def generation(self,path):
  s=Store(path);g=Generation(s,AI(),'blog');job=g.reserve('생성 테스트')
  p={'title':'제목','composed_content':'<p>'+('내용 '*600)+'</p>','labels':[]}
  from r3studio.finalize import corpus_hash,GATE_VERSION
  from test_generation import pack
  p['evidence']=pack();p['search_description']='검사된 검색설명'
  s.db.execute('INSERT INTO sync_runs(blog_id,started_at,finished_at,status) VALUES(?,?,?,?)',('blog',now(),now(),'DONE'));s.db.commit()
  p['final']={'gate_version':GATE_VERSION,'evidence_hash':digest(p['evidence']),'metadata_hash':digest({'labels':p['labels'],'search_description':p['search_description']}),'corpus_hash':corpus_hash([]),'grade':'PASS','article_hash':digest({'title':p['title'],'content':p['composed_content']}),'checked_at':now()};g.save(job,'최종 검사','PASS',p)
  return s,g,job
 def test_draft_and_no_duplicate(self):
  with tempfile.TemporaryDirectory() as d:
   s,g,j=self.generation(d+'/db');a=Adapter();publisher=Publisher(g,a)
   r=publisher.execute(prepare(g,j));self.assertEqual(r['status'],'DRAFT')
   publisher.execute(prepare(g,j));self.assertEqual(a.inserts,1);s.close()
 def test_evidence_change_revokes_publication(self):
  with tempfile.TemporaryDirectory() as d:
   s,g,j=self.generation(d+'/db');p=g.load_job(j)['payload'];p['evidence']['facts'][0]['text']='다른 주장';g.save(j,'변경','PASS',p)
   with self.assertRaises(PublishHold):prepare(g,j)
   s.close()
 def test_metadata_change_revokes_publication(self):
  with tempfile.TemporaryDirectory() as d:
   s,g,j=self.generation(d+'/db');p=g.load_job(j)['payload'];p['search_description']='변경된 설명';g.save(j,'변경','PASS',p)
   with self.assertRaises(PublishHold):prepare(g,j)
   s.close()
 def test_schedule_reuses_verified_draft(self):
  with tempfile.TemporaryDirectory() as d:
   s,g,j=self.generation(d+'/db');a=Adapter();pub=Publisher(g,a);pub.execute(prepare(g,j))
   from r3studio.sync import Sync
   Sync(s,a,'blog').run()
   when=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
   r=pub.execute(prepare(g,j,'SCHEDULED',when));self.assertEqual(r['status'],'SCHEDULED');self.assertEqual(a.inserts,1);self.assertEqual(a.publishes,1);s.close()
 def test_hold_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   s,g,j=self.generation(d+'/db');g.save(j,'미완료','HOLD',g.load_job(j)['payload'])
   with self.assertRaises(PublishHold):prepare(g,j)
   s.close()
 def test_timeout_no_duplicate_retry(self):
  with tempfile.TemporaryDirectory() as d:
   s,g,j=self.generation(d+'/db');a=Adapter();a.fail=True;pub=Publisher(g,a)
   with self.assertRaises(TimeoutError):pub.execute(prepare(g,j))
   with self.assertRaises(PublishHold):pub.execute(prepare(g,j))
   self.assertEqual(a.inserts,1);s.close()
 def test_image_output_prepared(self):
  out=io.BytesIO();Image.new('RGB',(1024,576),(90,120,140)).save(out,format='JPEG');data=out.getvalue();calls=[]
  def transport(p):
   calls.append(p);return {'steps':[{'type':'model_output','content':[{'type':'image','data':base64.b64encode(data).decode()}]}]}
  g=Generator('key','image-model',transport);generated=g.image('장면')
  with Image.open(io.BytesIO(generated)) as im:self.assertEqual(im.size,(1024,576))
  self.assertLessEqual(len(generated),500*1024);self.assertEqual(calls[0]['response_format']['aspect_ratio'],'16:9')
 def test_no_image_rejected(self):
  with self.assertRaises(AIError):Generator('key','image-model',lambda p:{'outputs':[]}).image('장면')
 def test_new_unrelated_post_revokes_final_pass(self):
  with tempfile.TemporaryDirectory() as d:
   s,g,j=self.generation(d+'/db')
   s.db.execute('INSERT INTO posts(blog_id,post_id,status,url,content) VALUES(?,?,?,?,?)',('blog','other','LIVE','https://blog.example/other','new article'));s.db.commit()
   with self.assertRaises(PublishHold):prepare(g,j)
   s.close()
 def test_title_only_change_revokes_final_pass(self):
  from r3studio.finalize import corpus_hash
  with tempfile.TemporaryDirectory() as d:
   s,g,j=self.generation(d+'/db')
   s.db.execute('INSERT INTO posts(blog_id,post_id,title,status,url,content) VALUES(?,?,?,?,?,?)',('blog','other','기존 제목','LIVE','https://blog.example/other','same body'));s.db.commit()
   p=g.load_job(j)['payload'];posts=[dict(r) for r in s.db.execute('SELECT * FROM posts')];p['final']['corpus_hash']=corpus_hash(posts);g.save(j,'최종 검사','PASS',p)
   prepare(g,j)
   s.db.execute('UPDATE posts SET title=?',('달라진 제목',));s.db.commit()
   with self.assertRaises(PublishHold):prepare(g,j)
   s.close()
 def test_read_only_reconcile_after_lost_reply(self):
  with tempfile.TemporaryDirectory() as d:
   s,g,j=self.generation(d+'/db')
   class LostReply(Adapter):
    def create_draft(self,p):
     super().create_draft(p);raise TimeoutError()
    def request_status(self,request):return {'status':'DONE','action':'create_draft','result':{'blogId':'blog','postId':'1'}}
   a=LostReply();pub=Publisher(g,a)
   with self.assertRaises(TimeoutError):pub.execute(prepare(g,j))
   result=pub.reconcile(j);self.assertEqual(result['status'],'DRAFT');self.assertEqual(a.inserts,1);self.assertEqual(a.publishes,0)
   pub.execute(prepare(g,j));self.assertEqual(a.inserts,1);s.close()
 def test_unfinished_server_journal_never_retries(self):
  with tempfile.TemporaryDirectory() as d:
   s,g,j=self.generation(d+'/db');a=Adapter();a.fail=True;a.request_status=lambda request:{'status':'RUNNING'};pub=Publisher(g,a)
   with self.assertRaises(TimeoutError):pub.execute(prepare(g,j))
   with self.assertRaises(PublishHold):pub.reconcile(j)
   self.assertEqual(a.inserts,1);self.assertEqual(s.db.execute('SELECT status FROM publish_history').fetchone()[0],'NEEDS_RECONCILE');s.close()
 def test_reconcile_rejects_changed_remote_body(self):
  with tempfile.TemporaryDirectory() as d:
   s,g,j=self.generation(d+'/db')
   class Changed(Adapter):
    def create_draft(self,p):
     super().create_draft(p);self.post['content']='changed';raise TimeoutError()
    def request_status(self,request):return {'status':'DONE','action':'create_draft','result':{'blogId':'blog','postId':'1'}}
   a=Changed();pub=Publisher(g,a)
   with self.assertRaises(TimeoutError):pub.execute(prepare(g,j))
   with self.assertRaises(PublishHold):pub.reconcile(j)
   self.assertEqual(a.inserts,1);s.close()
if __name__=='__main__':unittest.main()

