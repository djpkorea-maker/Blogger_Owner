import json
import unittest
from unittest.mock import patch
from r3studio.sync import Store,Sync,now
from r3studio.gates import run_checks
from r3studio.finalize import existing_review_hash
from r3studio.tasks import Cancelled
from r3studio.semantic import title_profile,body_review
from r3studio.titles import refill
from r3studio.evidence import EvidenceHold
from r3studio.imagegen import generate_candidates
from test_sync import Adapter

class Tests(unittest.TestCase):
 def test_cancelled_sync_does_not_replace_snapshot(self):
  s=Store(':memory:');a=Adapter();Sync(s,a,'blog').run()
  before=[tuple(r) for r in s.db.execute('SELECT * FROM posts')]
  a.posts['0']['updated']='v2';events=[]
  def progress(stage,i,n):
   events.append((stage,i,n))
   if n and i==1:raise Cancelled('사용자 중단')
  with self.assertRaises(Cancelled):Sync(s,a,'blog',progress=progress).run()
  self.assertEqual(before,[tuple(r) for r in s.db.execute('SELECT * FROM posts')])
  self.assertEqual(s.db.execute('SELECT count(*) FROM post_versions').fetchone()[0],3)
  self.assertTrue(events);s.close()
 def test_unrelated_draft_keeps_review_live_changes_revoke_it(self):
  s=Store(':memory:');a=Adapter();Sync(s,a,'blog').run();run_checks(s,'blog')
  def stamp():
   rows=[dict(r) for r in s.db.execute('SELECT * FROM posts')]
   row=next(r for r in rows if r['post_id']=='0')
   details={'review_context_hash':existing_review_hash(rows,'0'),'grade':'PASS','verified':True}
   s.db.execute('INSERT INTO recovery_checks(blog_id,post_id,content_hash,engine_version,checked_at,grade,details) VALUES(?,?,?,?,?,?,?)',('blog','0',row['content_hash'],'R3.0-existing-0.59',now(),'PASS',json.dumps(details)));s.db.commit()
  stamp();a.posts['2'].update(updated='v2',title='다른 초안 변경')
  Sync(s,a,'blog').run();run_checks(s,'blog')
  self.assertEqual(s.db.execute('SELECT grade FROM posts WHERE post_id="0"').fetchone()[0],'PASS')
  a.posts['3']={'id':'3','status':'LIVE','updated':'v1','title':'새 공개 글','content':'새 내용'}
  Sync(s,a,'blog').run();run_checks(s,'blog')
  self.assertEqual(s.db.execute('SELECT grade FROM posts WHERE post_id="0"').fetchone()[0],'NEEDS_DEEP');s.close()
 def test_semantic_duplicate_is_refilled_even_with_different_words(self):
  class AI:
   def __init__(self):self.titles=iter(['다른 표현의 같은 질문','독립적인 활용 질문'])
   def object(self,p):
    if 'R3 SEMANTIC TITLE' in p:
     duplicate='다른 표현의 같은 질문' in json.loads(p.split('\n',1)[1])['title']
     return {'duplicate':duplicate,'reason':'같은 결론' if duplicate else '독립 결론','duplicate_ids':['post:1'] if duplicate else [],'profile':{'core_question':'질문','search_intent':'점검','h2':['방법'],'key_facts':['조건'],'practical_outcome':'사용'}}
    return {'title':next(self.titles)}
  ai=AI();peers=[{'id':'post:1','title':'원래 제목'}]
  def validator(title):
   r=title_profile(ai,'주제',title,peers)
   return r['reason'] if r['duplicate'] else None
  self.assertEqual(refill(ai,'주제',[],validator=validator),'독립적인 활용 질문')
 def test_untrusted_semantic_reply_is_not_accepted(self):
  class AI:
   def object(self,p):return {'duplicate':False,'reason':'ok','duplicate_ids':['invented']}
  with self.assertRaises(EvidenceHold):body_review(AI(),'제목','본문',[{'id':'1'}])
 def test_failed_text_blocks_image_calls(self):
  class G:
   def load_job(self,n):return {'payload':{'title':'제목','content':'본문','deep':{'review':{'fact':'FAIL'}}}}
  from r3studio.images import ImageHold
  with self.assertRaises(ImageHold):generate_candidates(G(),None,1,'unused')

if __name__=='__main__':unittest.main()
