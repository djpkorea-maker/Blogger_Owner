"""Prepared single-post updates with persistent audit and no blind retries."""
import json
import uuid
from .sync import post_hash,guard_apply,now,digest
from .gates import Document

def validate_plan(plan,blog_id,post_id=None):
    if (not isinstance(plan,dict) or plan.get('blog_id')!=blog_id
        or not isinstance(plan.get('post_id'),str) or not plan['post_id']
        or (post_id is not None and plan['post_id']!=post_id)
        or any(not isinstance(plan.get(k),str) or not plan[k] for k in ('request_id','expected_hash','expected_updated'))
        or not isinstance(plan.get('expected_url'),str)
        or not isinstance(plan.get('before'),dict) or not isinstance(plan.get('proposal'),dict)):
        raise ValueError('수정 기록 형식 또는 대상 불일치: 적용 중지')
    before=plan['before'];proposal=plan['proposal']
    if (str(before.get('id'))!=plan['post_id'] or post_hash(before)!=plan['expected_hash']
        or before.get('updated')!=plan['expected_updated'] or before.get('url','')!=plan['expected_url']
        or set(proposal)!={'title','content','labels'}
        or any(not isinstance(proposal.get(k),str) or not proposal[k].strip() for k in ('title','content'))
        or not isinstance(proposal.get('labels'),list) or any(not isinstance(x,str) for x in proposal['labels'])):
        raise ValueError('수정 기록 내용 불일치: 적용 중지')
    if plan.get('plan_hash')!=digest({k:v for k,v in plan.items() if k not in ('plan_hash','rollback_request_id')}):
        raise ValueError('검토한 수정 계획 변경 감지: 새 수정안 검토 필요')
    return plan

def load_plan(raw,blog_id,post_id):
    try:plan=json.loads(raw)
    except (ValueError,TypeError):raise ValueError('수정 기록 손상: 적용 중지') from None
    return validate_plan(plan,blog_id,post_id)

class Apply:
    def __init__(self,store,adapter):self.store,self.adapter=store,adapter
    def reconcile(self,audit_id):
        row=self.store.db.execute('SELECT * FROM apply_history WHERE id=? AND blog_id=?',(audit_id,self.adapter.blog_id)).fetchone()
        if not row or row['status'] not in ('SENDING','NEEDS_RECONCILE'):raise ValueError('결과 확인이 필요한 수정 기록을 선택하세요.')
        plan=load_plan(row['details'],self.adapter.blog_id,row['post_id']);journal=self.adapter.request_status(plan['request_id'])
        result=journal.get('result') or {}
        if journal.get('status')!='DONE' or journal.get('action')!='apply_update' or result.get('blogId')!=self.adapter.blog_id or str(result.get('postId'))!=row['post_id'] or not result.get('backupFileId') or result.get('verified') is not True:raise ValueError('서버 수정 결과 미확정: 재적용하지 않습니다.')
        after=self.adapter.get_post(row['post_id']);desired=dict(plan['before'],**plan['proposal'])
        if post_hash(after)!=post_hash(desired) or after.get('url')!=plan['expected_url'] or after.get('published')!=plan['before'].get('published') or result.get('afterHash')!=post_hash(after):raise ValueError('현재 글이 검증된 수정 결과와 다릅니다.')
        unreadable=0
        with self.store.db:
            self.store.db.execute('UPDATE apply_history SET actual_hash=?,status=?,backup_ref=? WHERE id=?',(post_hash(after),'VERIFIED',result['backupFileId'],audit_id))
            if self.store.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='repair_proposals'").fetchone():
                for proposal in self.store.db.execute('SELECT id,payload,post_id FROM repair_proposals WHERE blog_id=? AND post_id=? AND status IN ("APPLYING","NEEDS_RECONCILE")',(self.adapter.blog_id,row['post_id'])).fetchall():
                    try:
                        payload=json.loads(proposal['payload'])
                        if not isinstance(payload,dict):raise ValueError()
                        linked=validate_plan(payload.get('plan'),self.adapter.blog_id,row['post_id'])
                    except (ValueError,TypeError):
                        unreadable+=1;continue
                    if linked['request_id']==plan['request_id'] and linked['proposal']==plan['proposal']:
                        self.store.db.execute('UPDATE repair_proposals SET status="APPLIED" WHERE id=?',(proposal['id'],))
        return {'status':'VERIFIED','post_id':row['post_id'],'audit_id':audit_id,'backup_ref':result['backupFileId'],'unreadable_related_records':unreadable}
    def prepare(self,pid,title,content,labels=None):
        before=self.adapter.get_post(pid)
        doc=Document(content)
        if not title.strip() or len(content)<200 or not ''.join(doc.text).strip():raise ValueError('빈 제목/본문은 적용할 수 없습니다.')
        if doc.errors or 'h1' in doc.headings:raise ValueError('HTML 구조 검사 미통과')
        proposal={'title':title,'content':content,'labels':before.get('labels',[]) if labels is None else labels}
        if not isinstance(proposal['labels'],list) or any(not isinstance(x,str) for x in proposal['labels']):raise ValueError('라벨 형식 오류')
        plan={'post_id':str(pid),'blog_id':self.adapter.blog_id,'before':before,'expected_hash':post_hash(before),'expected_updated':before.get('updated',''),'expected_url':before.get('url',''),'proposal':proposal,'request_id':str(uuid.uuid4())}
        plan['plan_hash']=digest(plan)
        return plan
    def apply(self,plan):
        validate_plan(plan,self.adapter.blog_id)
        if plan['blog_id']!=self.adapter.blog_id:raise ValueError('블로그 불일치')
        current=self.adapter.get_post(plan['post_id']);guard_apply(plan['expected_hash'],current)
        if current.get('updated')!=plan['expected_updated']:raise ValueError('LIVE 수정 시각 변경: 적용 중지')
        if current.get('url','')!=plan['expected_url']:raise ValueError('LIVE 글 주소 변경: 적용 중지 · 최신 글 재조회 필요')
        if current.get('published')!=plan['before'].get('published'):raise ValueError('예약·발행 시각 변경: 적용 중지')
        db=self.store.db
        with db:
            audit=db.execute('INSERT INTO apply_history(blog_id,post_id,created_at,expected_hash,actual_hash,status,backup_ref,details) VALUES(?,?,?,?,?,?,?,?)',(plan['blog_id'],plan['post_id'],now(),plan['expected_hash'],post_hash(current),'SENDING','',json.dumps(plan,ensure_ascii=False))).lastrowid
        try:
            reply=self.adapter.apply_update(plan)
            after=self.adapter.get_post(plan['post_id'])
            desired=dict(current,**plan['proposal'])
            if post_hash(after)!=post_hash(desired) or after.get('url')!=plan['expected_url'] or after.get('published')!=current.get('published'):
                raise ValueError('저장 결과 불일치: 자동 재시도 없이 확인 필요')
            status='VERIFIED'
        except Exception:
            with db:db.execute('UPDATE apply_history SET status=? WHERE id=?',('NEEDS_RECONCILE',audit))
            raise
        with db:db.execute('UPDATE apply_history SET actual_hash=?,status=?,backup_ref=? WHERE id=?',(post_hash(after),status,reply.get('backupFileId',''),audit))
        return {'status':status,'post_id':plan['post_id'],'audit_id':audit,'backup_ref':reply.get('backupFileId','')}

class WriteBridgeMixin:
    def request_status(self,request_id):
        return self._call('request_status',{'requestId':request_id})
    def apply_update(self,plan):
        return self._call('apply_update',{'confirm':'APPLY_ONE_POST','postId':plan['post_id'],'expectedHash':plan['expected_hash'],'expectedUpdated':plan['expected_updated'],'expectedUrl':plan['expected_url'],'requestId':plan['request_id'],**plan['proposal']})
    def upload_image(self,data,mime,name,request_id):
        import base64
        return self._call('upload_image',{'confirm':'UPLOAD_ONE_IMAGE','base64':base64.b64encode(data).decode('ascii'),'mimeType':mime,'fileName':name,'requestId':request_id})
    def rollback(self,pid,backup_ref,expected_hash,expected_updated,request_id):
        return self._call('rollback',{'confirm':'ROLLBACK_ONE_POST','postId':pid,'backupFileId':backup_ref,'expectedHash':expected_hash,'expectedUpdated':expected_updated,'requestId':request_id})
    def create_draft(self,plan):
        return self._call('create_draft',{'confirm':'CREATE_PASS_DRAFT','requestId':plan['draft_request_id'],'title':plan['title'],'content':plan['content'],'labels':plan['labels']})
    def publish_post(self,post,plan):
        return self._call('publish_pass',{'confirm':'PUBLISH_PASS_POST','requestId':plan['publish_request_id'],'postId':post['id'],'expectedHash':post_hash(post),'expectedUpdated':post['updated'],'mode':plan['mode'],'publishDate':plan['schedule']})
