"""PASS-only draft and publish plans, freshness checks and GET reconcile."""
import json
import uuid
from datetime import datetime,timezone
from .sync import digest,post_hash,now
from .freshness import is_fresh

class PublishHold(RuntimeError):pass

def schedule_matches(actual,expected):
    def parse(value):
        if not isinstance(value,str):raise ValueError()
        date=datetime.fromisoformat(value)
        if date.tzinfo is None:raise ValueError()
        return date.astimezone(timezone.utc)
    try:return parse(actual)==parse(expected)
    except (ValueError,TypeError,OverflowError):
        raise PublishHold('예약 시각 응답 누락 또는 형식 오류: 재확인 필요') from None

def validate_publish_plan(plan):
    if (not isinstance(plan,dict) or any(not isinstance(plan.get(k),str) or not plan[k]
        for k in ('blog_id','title','content','draft_request_id','publish_request_id','article_hash','checked_at'))
        or type(plan.get('job_id')) is not int or plan['job_id']<=0
        or plan.get('mode') not in ('DRAFT','LIVE','SCHEDULED')
        or not isinstance(plan.get('labels'),list)
        or any(not isinstance(label,str) for label in plan['labels'])
        or plan.get('plan_hash')!=digest({k:v for k,v in plan.items() if k!='plan_hash'})):
        raise PublishHold('저장 계획 기록 불일치: 적용 중지')
    if plan['article_hash']!=digest({'title':plan['title'],'content':plan['content']}):raise PublishHold('저장 계획 본문 hash 불일치')
    if plan['mode']=='SCHEDULED':schedule_matches(plan.get('schedule'),plan.get('schedule'))
    elif plan.get('schedule') is not None:raise PublishHold('저장 방식과 예약 시각 불일치')
    return plan

def saved_record(raw,verified=False):
    try:record=json.loads(raw)
    except (ValueError,TypeError):raise PublishHold('저장 기록 손상: 적용하지 말고 기록 확인이 필요합니다.') from None
    if not isinstance(record,dict):raise PublishHold('저장 기록 형식 오류: 적용 중지')
    validate_publish_plan(record.get('plan',record))
    if verified:
        result=record.get('result')
        if (not isinstance(result,dict) or not isinstance(result.get('post_id'),str)
            or not result['post_id'] or result.get('status') not in ('DRAFT','LIVE','SCHEDULED')
            or not isinstance(result.get('url',''),str)):
            raise PublishHold('저장 완료 기록 불확실: 새 글 생성 없이 확인 필요')
    return record

def own_post_id(store,job_id):
    if not store.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='publish_history'").fetchone():return None
    row=store.db.execute('SELECT payload FROM publish_history WHERE job_id=? AND status="VERIFIED" ORDER BY id DESC LIMIT 1',(job_id,)).fetchone()
    return saved_record(row[0],verified=True)['result']['post_id'] if row else None

def prepare(generation,job_id,mode='DRAFT',schedule=None):
    try:job=generation.load_job(job_id)
    except (ValueError,TypeError):raise PublishHold('생성 작업 기록 확인 필요: 저장/발행 중지') from None
    p=job['payload'];final=p.get('final',{})
    if not isinstance(final,dict):raise PublishHold('최종 검사 기록 형식 오류: 재검사 필요')
    if job['status']!='PASS' or final.get('grade')!='PASS':raise PublishHold('최종 PASS 글만 저장/발행 가능합니다.')
    if (any(not isinstance(p.get(k),str) or not p[k].strip() for k in ('title','composed_content','search_description'))
        or len(p['search_description'])>150 or not isinstance(p.get('labels',[]),list)
        or any(not isinstance(label,str) for label in p.get('labels',[]))):
        raise PublishHold('최종 글 또는 라벨·검색설명 형식 오류: 재검사 필요')
    if final.get('article_hash')!=digest({'title':p['title'],'content':p.get('composed_content','')}):raise PublishHold('최종 검사 이후 본문 변경')
    from .finalize import corpus_hash,GATE_VERSION
    if final.get('gate_version')!=GATE_VERSION:raise PublishHold('최종 검사 기준 변경: 다시 검사하세요.')
    from .sources import require_originals
    from .evidence import validate_pack,EvidenceHold
    try:validate_pack(p.get('evidence'));require_originals(p['evidence'])
    except EvidenceHold:raise PublishHold('근거 원문 검사 재확인 필요') from None
    if final.get('evidence_hash')!=digest(p['evidence']):raise PublishHold('최종 검사 이후 근거 변경')
    if final.get('metadata_hash')!=digest({'labels':p.get('labels',[]),'search_description':p.get('search_description')}):raise PublishHold('최종 검사 이후 라벨 또는 검색설명 변경')
    excluded=own_post_id(generation.store,job_id)
    posts=[dict(r) for r in generation.store.db.execute('SELECT post_id,title,status,url,content FROM posts WHERE blog_id=? AND present=1',(generation.blog_id,)) if r['post_id']!=excluded]
    if final.get('corpus_hash')!=corpus_hash(posts):raise PublishHold('최종 검사 이후 LIVE 목록 변경: 다시 검사하세요.')
    latest=generation.store.db.execute('SELECT status,finished_at FROM sync_runs WHERE blog_id=? ORDER BY id DESC LIMIT 1',(generation.blog_id,)).fetchone()
    if not latest or latest['status']!='DONE' or not is_fresh(latest['finished_at'],300):raise PublishHold('최근 5분 내 성공한 LIVE 동기화 필요')
    if not is_fresh(final.get('checked_at'),3600):raise PublishHold('최종 검사 유효기간 오류: 재검사 필요')
    if mode not in ('DRAFT','LIVE','SCHEDULED'):raise PublishHold('잘못된 저장 방식')
    if mode=='SCHEDULED':
        try:date=datetime.fromisoformat(schedule)
        except (ValueError,TypeError):raise PublishHold('예약 시간을 시간대 포함 ISO 형식으로 입력하세요.') from None
        if date.tzinfo is None or (date-datetime.now(timezone.utc)).total_seconds()<120:raise PublishHold('미래 예약 시각과 시간대 필요')
        schedule=date.astimezone(timezone.utc).isoformat()
    plan={'job_id':job_id,'blog_id':generation.blog_id,'mode':mode,'schedule':schedule,'title':p['title'],'content':p['composed_content'],'labels':p.get('labels',[]),'article_hash':final['article_hash'],'checked_at':final['checked_at'],'draft_request_id':str(uuid.uuid4()),'publish_request_id':str(uuid.uuid4())}
    plan['plan_hash']=digest(plan)
    return plan

class Publisher:
    def __init__(self,generation,adapter):self.generation,self.adapter=generation,adapter
    def reconcile(self,job_id):
        db=self.generation.store.db
        if not db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='publish_history'").fetchone():raise PublishHold('확인할 저장 기록이 없습니다.')
        row=db.execute('SELECT * FROM publish_history WHERE job_id=? ORDER BY id DESC LIMIT 1',(job_id,)).fetchone()
        if not row:raise PublishHold('확인할 저장 기록이 없습니다.')
        saved=saved_record(row['payload'],verified=row['status']=='VERIFIED');plan=saved.get('plan',saved)
        if plan['blog_id']!=self.adapter.blog_id:raise PublishHold('블로그 불일치')
        if row['status']=='VERIFIED':
            result=saved['result'];post=self.adapter.get_post(result['post_id'])
            expected={'title':plan['title'],'content':plan['content'],'labels':plan['labels'],'status':result['status']}
            if post_hash(post)!=post_hash(expected) or post.get('url','')!=result.get('url',''):raise PublishHold('현재 글이 이전 저장 기록과 다릅니다. 최신 상태 재확인 필요')
            if result['status']=='SCHEDULED' and not schedule_matches(post.get('published'),plan.get('schedule')):raise PublishHold('예약 시각 변경 감지')
            return result
        request=plan['draft_request_id'] if plan['mode']=='DRAFT' else plan['publish_request_id']
        journal=self.adapter.request_status(request)
        if journal.get('status')!='DONE':raise PublishHold('서버 저장 결과 미확정: 새 요청 없이 확인을 유지합니다.')
        expected_action='create_draft' if plan['mode']=='DRAFT' else 'publish_pass'
        result=journal.get('result',{})
        if journal.get('action')!=expected_action or result.get('blogId')!=plan['blog_id'] or not result.get('postId'):raise PublishHold('서버 요청 기록 불일치')
        post=self.adapter.get_post(str(result['postId']))
        expected={'title':plan['title'],'content':plan['content'],'labels':plan['labels'],'status':plan['mode']}
        if post_hash(post)!=post_hash(expected):raise PublishHold('현재 Blogger 글이 저장 계획과 다릅니다. 재확인 필요')
        if plan['mode']=='SCHEDULED' and not schedule_matches(post.get('published'),plan.get('schedule')):raise PublishHold('실제 예약 시각 불일치')
        verified={'post_id':post['id'],'status':post['status'],'url':post.get('url',''),'audit_id':row['id']}
        with db:db.execute('UPDATE publish_history SET status=?,payload=? WHERE id=?',('VERIFIED',json.dumps({'plan':plan,'result':verified},ensure_ascii=False),row['id']))
        return verified
    def execute(self,plan):
        validate_publish_plan(plan)
        if plan.get('plan_hash')!=digest({k:v for k,v in plan.items() if k!='plan_hash'}):raise PublishHold('저장 계획 변경 감지: 새 계획을 검토하세요.')
        if plan['blog_id']!=self.adapter.blog_id:raise PublishHold('블로그 불일치')
        # Re-evaluate freshness and state, including changed or revoked PASS.
        fresh=prepare(self.generation,plan['job_id'],plan['mode'],plan['schedule'])
        if any(plan[k]!=fresh[k] for k in ('article_hash','title','content','labels')):raise PublishHold('검토한 저장 계획이 변경됨')
        db=self.generation.store.db
        db.execute('CREATE TABLE IF NOT EXISTS publish_history(id INTEGER PRIMARY KEY,job_id INTEGER,created_at TEXT,status TEXT,payload TEXT)');db.commit()
        previous=db.execute('SELECT status,payload FROM publish_history WHERE job_id=? ORDER BY id DESC LIMIT 1',(plan['job_id'],)).fetchone()
        existing_id=None
        if previous:
            if previous['status']!='VERIFIED':raise PublishHold('이 작업의 이전 저장 결과 확인 필요: 자동 재시도 금지')
            record=saved_record(previous['payload'],verified=True);existing_id=record['result']['post_id']
            old_post=self.adapter.get_post(existing_id)
            expected_old={'title':plan['title'],'content':plan['content'],'labels':plan['labels'],'status':old_post['status']}
            if post_hash(old_post)!=post_hash(expected_old):raise PublishHold('저장된 글이 변경됨: 새 글 중복 생성 중지')
            if old_post['status']==plan['mode']:
                if plan['mode']!='SCHEDULED' or schedule_matches(old_post.get('published'),plan.get('schedule')):return record['result']
            if old_post['status']!='DRAFT':raise PublishHold('기존 글이 이미 발행/예약됨: 별도 변경 작업 필요')
        with db:audit=db.execute('INSERT INTO publish_history(job_id,created_at,status,payload) VALUES(?,?,?,?)',(plan['job_id'],now(),'SENDING',json.dumps(plan,ensure_ascii=False))).lastrowid
        try:
            draft={'postId':existing_id} if existing_id else self.adapter.create_draft(plan)
            post=self.adapter.get_post(draft['postId']);expected={'title':plan['title'],'content':plan['content'],'labels':plan['labels'],'status':'DRAFT'}
            if post_hash(post)!=post_hash(expected):raise PublishHold('초안 저장 GET 검증 실패')
            if plan['mode']!='DRAFT':
                self.adapter.publish_post(post,plan)
                post=self.adapter.get_post(post['id']);expected['status']=plan['mode']
                if post_hash(post)!=post_hash(expected):raise PublishHold('발행/예약 GET 검증 실패')
                if plan['mode']=='SCHEDULED' and not schedule_matches(post.get('published'),plan.get('schedule')):raise PublishHold('실제 예약 시각 불일치')
            result={'post_id':post['id'],'status':post['status'],'url':post.get('url',''),'audit_id':audit}
            with db:db.execute('UPDATE publish_history SET status=?,payload=? WHERE id=?',('VERIFIED',json.dumps({'plan':plan,'result':result},ensure_ascii=False),audit))
            return result
        except Exception:
            with db:db.execute('UPDATE publish_history SET status=? WHERE id=?',('NEEDS_RECONCILE',audit))
            raise
