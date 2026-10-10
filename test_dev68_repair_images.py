import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from r3studio.repair_images import RepairImages,replace_slot
from r3studio.images import ImageHold,inspect_bytes
from r3studio.sync import Store,post_hash,now
from r3studio.recovery import Recovery,RecoveryHold
from r3studio.preview import preview_parts
from test_images import image
from test_public_images import CONTENT

class Tests(unittest.TestCase):
 def setup_case(self,d,status='PASS'):
  s=Store(':memory:');before={'id':'1','title':'가전 점검','content':CONTENT,'status':'LIVE','updated':'v1','url':'https://blog.example/post'}
  a=SimpleNamespace(blog_id='blog',get_post=lambda pid:dict(before))
  Recovery(s,None,a)
  payload={'before':before,'expected_hash':post_hash(before),'proposed_content':CONTENT,'plan':{},'proposal_hash':'old-pass'}
  pid=s.db.execute('INSERT INTO repair_proposals(blog_id,post_id,created_at,status,payload) VALUES(?,?,?,?,?)',('blog','1',now(),status,json.dumps(payload))).lastrowid;s.db.commit()
  data=image();path=Path(d)/'candidate.image';path.write_bytes(data)
  c={'result':'PASS','file':str(path),'info':inspect_bytes(data),'alt':'실제 픽셀에 맞는 가전제품','caption':'실제 픽셀에 보이는 가전제품의 점검 모습입니다.','edit_mode':'replace'}
  return s,a,pid,c
 def test_unrelated_candidate_cannot_be_selected(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid,c=self.setup_case(d);service=RepairImages(s,a,None,d)
   c['result']='HOLD';row,p=service.load(pid);p['image_edit_candidates']={'1':c};service.save(pid,p)
   with self.assertRaises(ImageHold):service.operate(pid,'choose')
   self.assertNotIn('1',service.load(pid)[1].get('image_choices',{}));s.close()
 def test_choose_invalidates_pass_and_cancel_restores_original_without_writes(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid,c=self.setup_case(d);service=RepairImages(s,a,None,d);row,p=service.load(pid);p['image_edit_candidates']={'1':c};service.save(pid,p)
   result=service.operate(pid,'choose');self.assertEqual(result['status'],'HOLD');self.assertNotIn('plan',result)
   with self.assertRaises(RecoveryHold):Recovery(s,None,a).apply_proposal(pid)
   result=service.operate(pid,'cancel');self.assertEqual(result['proposed_content'],CONTENT);self.assertFalse(result['image_choices']);s.close()
 def test_candidate_file_change_blocks_choose(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid,c=self.setup_case(d);service=RepairImages(s,a,None,d);row,p=service.load(pid);p['image_edit_candidates']={'1':c};service.save(pid,p)
   Path(c['file']).write_bytes(b'changed')
   with self.assertRaises(ImageHold):service.operate(pid,'choose')
   s.close()
 def test_import_checks_actual_pixels_against_current_article(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid,c=self.setup_case(d);service=RepairImages(s,a,None,d)
   with patch('r3studio.repair_images.ImageQA.check',return_value=(c,False)) as qa:result=service.operate(pid,'import',path=c['file'])
   self.assertEqual(qa.call_args.args[2],CONTENT);self.assertNotIn('1',result['image_choices']);self.assertEqual(result['status'],'HOLD');s.close()
 def test_alt_regeneration_bypasses_old_qa_cache(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid,c=self.setup_case(d);service=RepairImages(s,a,None,d)
   with patch('r3studio.repair_images.ImageQA.check',return_value=(c,False)) as qa:service.operate(pid,'alt',download=lambda u:image())
   self.assertTrue(qa.call_args.kwargs['force']);s.close()
 def test_replace_keeps_other_image_body_and_escapes_text(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid,c=self.setup_case(d);url='https://lh3.googleusercontent.com/new';receipt={'ok':True,'publicImageUrl':url,'byte_hash':c['info']['byte_hash']}
   result=replace_slot(CONTENT,1,'https://lh3.googleusercontent.com/a',c,receipt)
   from r3studio.gates import Document
   old=Document(CONTENT).images;new=Document(result).images
   self.assertEqual(new[0]['src'],url);self.assertEqual(new[1],old[1]);self.assertIn(c['caption'],result);s.close()
 def test_mixed_body_or_multiple_images_block_automatic_replacement(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid,c=self.setup_case(d);r={'ok':True,'publicImageUrl':'https://lh3.googleusercontent.com/new','byte_hash':c['info']['byte_hash']}
   for content in ['<p>본문<img src="a"></p>','<figure><img src="a"><img src="b"></figure>','<figure><img src="a"><p>일반 본문</p><figcaption>설명</figcaption></figure>']:
    with self.assertRaises(ImageHold):replace_slot(content,1,'a',c,r)
   s.close()
 def test_preview_selected_pixels_not_claimed_as_applied_html(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid,c=self.setup_case(d);choices={'1':{'candidate':c,'expected_url':'https://lh3.googleusercontent.com/a','mode':'replace'}}
   part=next(p for p in preview_parts(CONTENT,proposed=True,choices=choices) if p['kind']=='image')
   self.assertTrue(part['selected_candidate']);self.assertEqual(part['alt'],c['alt']);self.assertEqual(part['src'],choices['1']['expected_url']);s.close()
 def test_failed_candidate_can_be_viewed_but_is_marked_hold(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid,c=self.setup_case(d);c['result']='HOLD';c.pop('alt');c.pop('caption')
   part=next(p for p in preview_parts(CONTENT,proposed=True,choices={'1':{'candidate':c,'expected_url':'https://lh3.googleusercontent.com/a','preview_only':True}}) if p['kind']=='image')
   self.assertEqual(part['candidate_status'],'HOLD');self.assertEqual(part['preview_file'],c['file']);s.close()
 def test_stale_review_cannot_apply_newer_proposal(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid,c=self.setup_case(d)
   with self.assertRaisesRegex(RecoveryHold,'검토 이후 수정안 변경'):Recovery(s,None,a).apply_proposal(pid,expected_proposal_hash='different-reviewed-version')
   s.close()
 def test_generation_is_one_attempt_and_uses_current_article(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid,c=self.setup_case(d);calls=[]
   ai=SimpleNamespace(object=lambda prompt:(calls.append(prompt) or {'prompt':'가전 점검 장면'}))
   generated=[];generator=SimpleNamespace(image=lambda prompt:(generated.append(prompt) or image()))
   service=RepairImages(s,a,ai,d)
   with patch('r3studio.repair_images.ImageQA.check',return_value=(c,False)):result=service.operate(pid,'generate',generator=generator)
   self.assertEqual(len(generated),1);self.assertIn('가전 점검',calls[0]);self.assertEqual(result['status'],'HOLD');self.assertFalse(result['image_choices']);s.close()
 def test_selected_alt_still_requires_strict_body_and_public_pixel_validation(self):
  from r3studio.evidence import EvidenceHold
  with tempfile.TemporaryDirectory() as d:
   s,a,pid,c=self.setup_case(d);service=RepairImages(s,a,None,d);row,p=service.load(pid)
   p['image_choices']={'1':{'candidate':c,'expected_url':'https://lh3.googleusercontent.com/a','mode':'text'}};service.save(pid,p)
   with patch('r3studio.repair_images.collect_cached',side_effect=EvidenceHold('수정 본문 근거 보류')) as collect:result=service.validate(pid)
   self.assertEqual(result['status'],'HOLD');self.assertNotIn('plan',result);self.assertIn(c['alt'],collect.call_args.kwargs['article'])
   self.assertNotIn('allow_partial',collect.call_args.kwargs)
   with self.assertRaises(RecoveryHold):Recovery(s,None,a).apply_proposal(pid)
   s.close()
 def test_uncertain_upload_reconciles_without_replay_and_never_passes(self):
  with tempfile.TemporaryDirectory() as d:
   s,a,pid,c=self.setup_case(d);calls=[];a.request_status=lambda rid:(calls.append(rid) or {'status':'RUNNING'})
   service=RepairImages(s,a,None,d);row,p=service.load(pid);p['image_choices']={'1':{'candidate':c,'expected_url':'https://lh3.googleusercontent.com/a','mode':'replace','request_id':'old-request'}};service.save(pid,p)
   with patch('r3studio.repair_images.upload_checked',side_effect=AssertionError('중복 업로드')):result=service.validate(pid)
   self.assertEqual(calls,['old-request']);self.assertEqual(result['status'],'HOLD');self.assertIn('재업로드하지 않습니다',result['reason']);s.close()
if __name__=='__main__':unittest.main()
