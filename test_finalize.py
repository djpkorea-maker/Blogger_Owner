import unittest
from r3studio.links import check_links,LinkHold
from r3studio.finalize import decide,FinalHold
from r3studio.sync import digest
from test_generation import pack,Fake
class Tests(unittest.TestCase):
 def fixture(self):
  text=' '.join(f'점검 순서 {i}에서는 사용 조건과 표시를 확인하고 전원 상태를 기록합니다.' for i in range(70))
  content='<h2>점검 순서</h2><p>'+text+'</p><h2>확인 조건</h2><p>조건을 비교합니다.</p>'
  for n in (1,2):content+=f'<figure><img src="https://lh3.googleusercontent.com/d/img{n}" alt="용기 모양"><figcaption>실제 용기 모양을 보여줍니다.</figcaption></figure>'
  content+='<a href="https://blog.example/live">관련 점검</a><a href="https://manufacturer.example/manual">설명서</a>'
  payload={'title':'점검 순서 확인','composed_content':content,'evidence':pack(),'search_description':'사용 조건 점검 순서','independent_fact_search':{'citations':[{'url':'https://manufacturer.example/manual'}]}}
  h=digest({'title':payload['title'],'content':content});payload['final_fact_article_hash']=h
  images=[{'result':'PASS','url':f'https://lh3.googleusercontent.com/d/img{n}','alt':'용기 모양','article_hash':h} for n in (1,2)]
  posts=[{'post_id':'1','title':'관련 점검','content':'다른 글','status':'LIVE','url':'https://blog.example/live'}]
  return payload,images,posts
 def fetch(self,url):return {'status':200,'url':url,'body':'','headers':{},'redirects':[]}
 def test_all_checks_can_pass(self):
  p,images,posts=self.fixture();r=decide(Fake(),p,posts,'https://blog.example/',images,self.fetch)
  self.assertEqual(r['grade'],'PASS')
 def test_unchecked_images_block(self):
  p,_,posts=self.fixture()
  with self.assertRaises(FinalHold):decide(Fake(),p,posts,'https://blog.example/',[],self.fetch)
 def test_modified_article_blocks_old_fact(self):
  p,images,posts=self.fixture();p['final_fact_article_hash']='old'
  with self.assertRaises(FinalHold):decide(Fake(),p,posts,'https://blog.example/',images,self.fetch)
 def test_draft_link_blocked(self):
  p,_,posts=self.fixture();posts[0]['status']='DRAFT'
  with self.assertRaises(LinkHold):check_links(p['composed_content'],'https://blog.example/',posts,p['evidence'],self.fetch)
 def test_broken_source_link_blocks(self):
  p,_,posts=self.fixture()
  def fetch(url):return {'status':404,'url':url}
  with self.assertRaises(LinkHold):check_links(p['composed_content'],'https://blog.example/',posts,p['evidence'],fetch)
if __name__=='__main__':unittest.main()
