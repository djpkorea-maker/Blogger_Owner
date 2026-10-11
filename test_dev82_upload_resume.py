"""Exercise persisted Dev81 requests with the real Bridge client; no accounts."""
import base64
import copy
import hashlib
import json
import queue
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace

from r3studio.bridge import WriteBridgeAdapter,BridgeError,bridge_failure
from r3studio.layout import recover_upload,upload_context,LayoutHold
from r3studio.repair_images import RepairImages
from r3studio.images import inspect_bytes
from r3studio.sync import Store,now,post_hash,digest
from r3studio.recovery import Recovery
from r3studio.gates import Result
from r3studio.tasks import TaskLog,Cancellation,finish_validation
from r3studio.presentation import history_text
from test_images import image
from test_public_images import CONTENT

RID='11111111-1111-4111-8111-111111111111'
RID2='22222222-2222-4222-8222-222222222222'
URL='https://script.google.com/macros/s/EXAMPLE/exec'

class Server:
    def __init__(self):
        self.journals={};self.uploads=[];self.calls=[];self.timeout=False;self.reject=None
        self.post={'id':'1','title':'가전 점검','content':CONTENT,'status':'SCHEDULED',
                   'updated':'v1','url':'https://blog.example/post','published':'2030-01-01T00:00:00Z','labels':[]}
    def __call__(self,body):
        action=body['action'];p=body['payload'];self.calls.append(action)
        if action=='get_post':return {'ok':True,'blogId':'blog','post':copy.deepcopy(self.post)}
        if action=='request_status':return copy.deepcopy(self.journals.get(p['requestId'],{'ok':True,'blogId':'blog','status':'NOT_FOUND'}))
        if action=='upload_image':
            if self.reject:return {'ok':False,'error':self.reject}
            rid=p['requestId'];self.uploads.append(rid)
            data=base64.b64decode(p['base64'])
            receipt={'ok':True,'blogId':'blog','byte_hash':hashlib.sha256(data).hexdigest(),
                     'publicImageUrl':'https://lh3.googleusercontent.com/d/'+rid+'=w1024'}
            self.journals[rid]={'ok':True,'blogId':'blog','status':'DONE','action':'upload_image','result':receipt}
            if self.timeout:self.timeout=False;raise bridge_failure('TIMEOUT')
            return copy.deepcopy(receipt)
        raise AssertionError('No article write or other side effect allowed: '+action)

class Tests(unittest.TestCase):
    def candidate(self,d,name='one.image'):
        path=Path(d)/name;path.write_bytes(image())
        if name!='one.image':
            from PIL import Image
            Image.new('RGB',(1024,576),(30,110,190)).save(path,format='PNG')
        return {'result':'PASS','file':str(path),'info':inspect_bytes(path.read_bytes()),
                'alt':'실제 픽셀에 맞는 가전제품','caption':'실제 가전제품을 안전하게 점검하는 모습입니다.'}
    def client(self,server):return WriteBridgeAdapter(URL,'never-log-secret','blog',server)
    def fixture(self,d,store=None):
        s=store or Store(':memory:');server=Server();a=self.client(server);Recovery(s,None,a)
        candidates=[self.candidate(d),self.candidate(d,'two.image')]
        payload={'before':copy.deepcopy(server.post),'expected_hash':post_hash(server.post),'proposed_content':CONTENT,
                 'proposed_title':'가전 점검','image_choices':{str(i+1):{'candidate':c,'expected_url':u,'mode':'replace','request_id':rid}
                    for i,(c,u,rid) in enumerate(zip(candidates,['https://lh3.googleusercontent.com/a','https://lh3.googleusercontent.com/b'],[RID,RID2]))}}
        for slot,choice in payload['image_choices'].items():
            choice['candidate']['target']={'slot':int(slot),'url':choice['expected_url'],'article_hash':digest(CONTENT)}
        with s.db:pid=s.db.execute('INSERT INTO repair_proposals(blog_id,post_id,created_at,status,payload) VALUES(?,?,?,?,?)',('blog','1',now(),'HOLD',json.dumps(payload))).lastrowid
        return s,server,a,RepairImages(s,a,None,d),pid
    def final_checks(self):
        stack=ExitStack()
        stack.enter_context(patch('r3studio.repair_images.collect_cached',return_value={}))
        stack.enter_context(patch('r3studio.repair_images.fast_check',return_value=Result('NEEDS_DEEP','DEEP',[],{})))
        stack.enter_context(patch('r3studio.fact_search.collect',return_value={}))
        stack.enter_context(patch('r3studio.repair_images.evaluate',return_value={'text_verified':True}))
        stack.enter_context(patch('r3studio.repair_images.check_public_images',return_value=[{'result':'PASS'},{'result':'PASS'}]))
        stack.enter_context(patch('r3studio.repair_images.check_links',return_value={'pass':True}))
        stack.enter_context(patch('r3studio.repair_images.Apply.prepare',side_effect=lambda *args:{
            'expected_hash':post_hash(Server().post),'expected_updated':'v1','expected_url':'https://blog.example/post',
            'proposal':{'title':args[1],'content':args[2],'labels':[]}}))
        return stack
    def test_legacy_no_start_record_resumes_both_slots_then_passes_without_article_write(self):
        with tempfile.TemporaryDirectory() as d:
            s,server,a,service,pid=self.fixture(d);old=copy.deepcopy(service.load(pid)[1])
            with self.final_checks():result=service.validate(pid)
            self.assertEqual(result['status'],'PASS');self.assertEqual(server.uploads,[RID,RID2])
            self.assertEqual(result['proposed_content'],old['proposed_content']);self.assertEqual(result['before'],old['before'])
            self.assertEqual([result['image_choices'][k]['request_id'] for k in ('1','2')],[RID,RID2])
            self.assertEqual([result['image_choices'][k]['candidate'] for k in ('1','2')],[old['image_choices'][k]['candidate'] for k in ('1','2')])
            self.assertEqual(len(result['upload_recovery_history']),6)
            with self.final_checks():again=service.validate(pid)
            self.assertEqual(again['status'],'PASS');self.assertEqual(server.uploads,[RID,RID2]);s.close()
    def test_timeout_after_server_finished_is_recovered_without_second_upload(self):
        with tempfile.TemporaryDirectory() as d:
            s,server,a,service,pid=self.fixture(d);server.timeout=True
            first=service.validate(pid)
            self.assertEqual(first['status'],'HOLD');self.assertEqual(first['error_diagnostic']['request_type'],'upload_image')
            self.assertNotIn('receipt',first['image_choices']['1']);self.assertEqual(server.uploads,[RID])
            with self.final_checks():second=service.validate(pid)
            self.assertEqual(second['status'],'PASS');self.assertEqual(server.uploads,[RID,RID2])
            self.assertNotIn('error_diagnostic',second);s.close()
    def test_done_server_receipt_is_reused(self):
        with tempfile.TemporaryDirectory() as d:
            server=Server();a=self.client(server);c=self.candidate(d)
            a.upload_image(Path(c['file']).read_bytes(),c['info']['mime'],Path(c['file']).name,RID)
            receipt=recover_upload(a,c,RID,1)
            self.assertEqual(server.uploads,[RID]);self.assertFalse(receipt['public_pixel_verified'])
    def test_running_unknown_and_malformed_states_never_upload(self):
        with tempfile.TemporaryDirectory() as d:
            c=self.candidate(d)
            for journal in [None,{'status':'RUNNING'}, {'status':'UNKNOWN'}, {'status':'NOT_FOUND'},
                            {'ok':False,'blogId':'blog','status':'NOT_FOUND'},
                            {'ok':True,'blogId':'other','status':'NOT_FOUND'},
                            {'ok':True,'blogId':'blog','status':'NOT_FOUND','result':{}},
                            {'ok':True,'blogId':'blog','status':'NOT_FOUND','action':'apply_update'}]:
                calls=[];a=SimpleNamespace(blog_id='blog',request_status=lambda rid:journal,upload_image=lambda *args:calls.append(args))
                with self.subTest(journal=journal),self.assertRaises(LayoutHold):recover_upload(a,c,RID,1)
                self.assertFalse(calls)
    def test_done_mismatch_never_uploads(self):
        with tempfile.TemporaryDirectory() as d:
            c=self.candidate(d);server=Server();a=self.client(server)
            a.upload_image(Path(c['file']).read_bytes(),c['info']['mime'],'one.image',RID)
            valid=copy.deepcopy(server.journals[RID])
            for field,value in [('action','apply_update'),('blogId','wrong'),('byte_hash','changed'),('publicImageUrl','https://example.com/x')]:
                bad=copy.deepcopy(valid)
                (bad if field=='action' else bad['result'])[field]=value
                server.journals[RID]=bad
                with self.subTest(field=field),self.assertRaises(LayoutHold):recover_upload(a,c,RID,1)
                self.assertEqual(server.uploads,[RID])
    def test_file_change_stops_before_status_lookup(self):
        with tempfile.TemporaryDirectory() as d:
            c=self.candidate(d);server=Server();Path(c['file']).write_bytes(image()[:-10])
            with self.assertRaises(Exception):recover_upload(self.client(server),c,RID,1)
            self.assertFalse(server.calls)
    def test_saved_endpoint_change_blocks_resume(self):
        with tempfile.TemporaryDirectory() as d:
            s,server,a,service,pid=self.fixture(d);_,p=service.load(pid)
            p['image_choices']['1']['upload_context']=dict(upload_context(a,p['image_choices']['1']['candidate']),bridge_url=URL+'changed')
            service.save(pid,p);result=service.validate(pid)
            self.assertEqual(result['status'],'HOLD');self.assertIn('대상·파일 기록 변경',result['reason'])
            self.assertNotIn('request_status',server.calls);self.assertFalse(server.uploads);s.close()
    def test_swapped_image_slots_block_before_status_or_upload(self):
        with tempfile.TemporaryDirectory() as d:
            s,server,a,service,pid=self.fixture(d);_,p=service.load(pid)
            one=p['image_choices']['1']['candidate'];two=p['image_choices']['2']['candidate']
            self.assertNotEqual(one['info']['pixel_hash'],two['info']['pixel_hash'])
            p['image_choices']['1']['candidate']=two;service.save(pid,p)
            result=service.validate(pid)
            self.assertEqual(result['status'],'HOLD');self.assertIn('이미지 번호·대상 변경',result['reason'])
            self.assertNotIn('request_status',server.calls);self.assertFalse(server.uploads);s.close()
    def test_rejection_preserves_request_and_exact_safe_reason(self):
        with tempfile.TemporaryDirectory() as d:
            s,server,a,service,pid=self.fixture(d);server.reject='writes_disabled'
            result=service.validate(pid)
            self.assertEqual(result['error_diagnostic']['server_code'],'writes_disabled')
            self.assertEqual(result['error_diagnostic']['stage'],'이미지 공개 업로드')
            self.assertEqual(result['image_choices']['1']['request_id'],RID);self.assertFalse(server.uploads)
            self.assertEqual(result['proposed_content'],CONTENT);s.close()
    def test_request_number_damage_does_not_create_new_request(self):
        with tempfile.TemporaryDirectory() as d:
            server=Server()
            with self.assertRaisesRegex(LayoutHold,'요청 번호 손상'):recover_upload(self.client(server),self.candidate(d),'bad-id',1)
            self.assertFalse(server.uploads)
    def test_cancel_after_status_check_does_not_upload(self):
        from r3studio.tasks import Cancelled
        with tempfile.TemporaryDirectory() as d:
            server=Server();token=Cancellation();events=[]
            def record(event):events.append(event);token.request()
            with self.assertRaises(Cancelled):recover_upload(self.client(server),self.candidate(d),RID,1,lambda *args:token.checkpoint(),record)
            self.assertFalse(server.uploads)
    def test_bridge_rejections_do_not_leak_unrecognized_server_text(self):
        for message in ['read_only_unknown_action','writes_disabled','image_sharing_failed','unknown raw token=https://example.com/private?secret=never-log-secret',None,{}]:
            a=self.client(lambda body:{'ok':False,'error':message})
            with self.subTest(message=message),self.assertRaises(BridgeError) as caught:a._call('upload_image',{})
            text=str(caught.exception)+json.dumps(caught.exception.diagnostic)
            self.assertNotIn('never-log-secret',text);self.assertNotIn('private?',text)
            self.assertEqual(caught.exception.diagnostic['request_type'],'upload_image')
            if message in ('read_only_unknown_action','writes_disabled','image_sharing_failed'):
                self.assertEqual(caught.exception.diagnostic['server_code'],message)
    def test_validation_hold_history_has_reason_and_is_not_completed(self):
        s=Store(':memory:');task=TaskLog(s,'수정안 최종 검증')
        finish_validation(task,{'status':'HOLD','reason':'이전 이미지 업로드 결과 미확정',
            'error_diagnostic':{'server_status':'RUNNING','image_slot':1}})
        row=s.db.execute('SELECT * FROM task_runs').fetchone()
        self.assertEqual(row['status'],'HOLD');text=history_text([row])
        self.assertIn('보류',text);self.assertIn('서버 업로드 상태: RUNNING',text);self.assertNotIn('작업 완료',text)
        self.assertTrue(row['finished_at']);s.close()
    def test_validation_worker_records_hold_without_false_completion(self):
        from r3studio.app import App
        with tempfile.TemporaryDirectory() as d:
            store=Store(str(Path(d)/'studio.sqlite3'));s,server,a,service,pid=self.fixture(d,store);s.close()
            app=App.__new__(App);app.base=Path(d);app.events=queue.Queue();app.cancel_token=Cancellation()
            app.sync_posts=lambda *args,**kwargs:None
            ai=SimpleNamespace(transport=lambda body:None)
            result={'proposal_id':pid,'status':'HOLD','reason':'이미지 업로드 미확정'}
            with patch('r3studio.readiness.require_settings'),patch('r3studio.bridge.BridgeAdapter.from_environment',return_value=a),patch('r3studio.bridge.WriteBridgeAdapter.from_environment',return_value=a),patch('r3studio.ai.Gemini.from_environment',return_value=ai),patch('r3studio.app.run_checks'),patch('r3studio.repair_images.RepairImages.validate',return_value=result):
                app.ai_worker('repair_validate',{'proposal_id':pid,'slot':1})
            s=Store(str(Path(d)/'studio.sqlite3'));row=s.db.execute('SELECT * FROM task_runs').fetchone()
            self.assertEqual(row['status'],'HOLD');self.assertIn('이미지 업로드 미확정',row['details']);s.close()

if __name__=='__main__':unittest.main()
