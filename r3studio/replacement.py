"""Generate a complete replacement tied to one existing post, never a new post."""
import json
from pathlib import Path
from copy import deepcopy
from .sync import now,digest,post_hash
from .generation import Generation
from .recovery import Recovery
from .repair_images import RepairImages
from .images import ImageHold,inspect_bytes
from .imagegen import generate_candidates
from .gates import Document
from .tasks import Cancelled
from .titles import normalize

def replacement_view(p):
    """Keep the requested topic distinct from an AI-generated title."""
    return {'topic':p.get('replacement_topic',''), 'title':p.get('proposed_title') or '아직 생성되지 않음',
            'stage':p.get('replacement_stage') or '생성 준비', 'reason':p.get('reason') or '결과 확인 필요',
            'has_body':bool(p.get('proposed_content','').strip()), 'can_resume':type(p.get('replacement_job_id')) is int}

def replacement_target(store,blog_id,payload):
    target=payload.get('replacement_target')
    if target is None:return None
    if (not isinstance(target,dict) or target.get('blog_id')!=str(blog_id) or not isinstance(target.get('post_id'),str)
        or type(target.get('proposal_id')) is not int or target['proposal_id']<=0):raise ImageHold('전체 교체 대상 기록 불일치')
    row=store.db.execute('SELECT post_id,payload,status FROM repair_proposals WHERE id=? AND blog_id=?',(target.get('proposal_id'),str(blog_id))).fetchone()
    if not row or row['post_id']!=target['post_id']:raise ImageHold('전체 교체 대상 수정안 없음')
    try:
        p=json.loads(row['payload'])
        if not isinstance(p,dict) or not isinstance(p.get('before'),dict):raise ValueError()
        if (p.get('mode')!='REPLACEMENT' or str(p['before'].get('id'))!=target['post_id']
            or p.get('expected_hash')!=target.get('expected_hash') or post_hash(p['before'])!=target.get('expected_hash')):raise ValueError()
    except (ValueError,TypeError,KeyError):raise ImageHold('전체 교체 원본 기록 불일치 또는 손상') from None
    return target

def saved_replacements(store,blog_id):
    if not store.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='repair_proposals'").fetchone():return []
    result=[]
    for row in store.db.execute('SELECT * FROM repair_proposals WHERE blog_id=? AND status IN ("HOLD","PASS") ORDER BY id DESC',(str(blog_id),)):
        try:
            p=json.loads(row['payload'])
            if p.get('mode')!='REPLACEMENT' or str(p['before']['id'])!=row['post_id'] or p.get('expected_hash')!=post_hash(p['before']):continue
            result.append({'proposal_id':row['id'],'status':row['status'],**p})
        except (ValueError,TypeError,KeyError):continue
    return result

def text_ready(payload):
    from .text_flow import ready
    return ready(payload)

class Replacement:
    def __init__(self,store,adapter,ai,cache_dir,progress=lambda *a:None):
        self.store,self.adapter,self.ai=store,adapter,ai;self.cache=Path(cache_dir);self.progress=progress
        Recovery(store,ai,adapter,progress)
        self.images=RepairImages(store,adapter,ai,cache_dir,progress)
    def matching_work(self,before,topic):
        for p in saved_replacements(self.store,self.adapter.blog_id):
            if (str(p['before']['id'])==str(before['id']) and normalize(p.get('replacement_topic',''))==normalize(topic)
                and p['expected_hash']==post_hash(before) and p['before'].get('updated')==before.get('updated')
                and p['before'].get('url','')==before.get('url','') and p['before'].get('published')==before.get('published')
                and type(p.get('replacement_job_id')) is int):
                # Never attach another post's or a new-publication job to this proposal.
                g=Generation(self.store,self.ai,self.adapter.blog_id,self.progress)
                target=replacement_target(self.store,self.adapter.blog_id,g.load_job(p['replacement_job_id'])['payload'])
                if target and target['proposal_id']==p['proposal_id']:return p
        return None
    def start_post(self,post_id,topic,generator):
        if not isinstance(topic,str) or not topic.strip():raise ImageHold('새로 작성할 주제를 입력하세요.')
        before=self.adapter.get_post(str(post_id))
        if str(before.get('id'))!=str(post_id):raise ImageHold('전체 교체 대상 글 번호 불일치')
        previous=self.matching_work(before,topic.strip())
        if previous:return self.resume(previous['proposal_id'],generator)
        original={'before':before,'expected_hash':post_hash(before),'reason':'전체 교체 전 원본 보관'}
        with self.store.db:
            seed=self.store.db.execute('INSERT INTO repair_proposals(blog_id,post_id,created_at,status,payload) VALUES(?,?,?,?,?)',(self.adapter.blog_id,str(post_id),now(),'HOLD',json.dumps(original,ensure_ascii=False))).lastrowid
        return self.start(seed,topic,generator)
    def start(self,proposal_id,topic,generator):
        if not isinstance(topic,str) or not topic.strip():raise ImageHold('새로 작성할 주제를 입력하세요.')
        _,old=self.images.load(proposal_id);self.images.baseline(old)
        previous=self.matching_work(old['before'],topic.strip())
        if previous:return self.resume(previous['proposal_id'],generator)
        p={'mode':'REPLACEMENT','before':old['before'],'expected_hash':old['expected_hash'],'replacement_topic':topic.strip(),'site_url':old['before'].get('url','') or next((r[0] for r in self.store.db.execute('SELECT url FROM posts WHERE blog_id=? AND present=1 AND status="LIVE" AND url!=""',(self.adapter.blog_id,))),''),'changes':['제목·본문·이미지 2장·ALT·그림 설명 전체 교체'],'reason':'전체 교체 생성 준비 · Blogger 미반영'}
        with self.store.db:
            pid=self.store.db.execute('INSERT INTO repair_proposals(blog_id,post_id,created_at,status,payload) VALUES(?,?,?,?,?)',(self.adapter.blog_id,str(p['before']['id']),now(),'HOLD',json.dumps(p,ensure_ascii=False))).lastrowid
        try:
            p['replacement_stage']='주제 작업 예약'
            g=Generation(self.store,self.ai,self.adapter.blog_id,self.progress)
            target={'proposal_id':pid,'blog_id':self.adapter.blog_id,'post_id':str(p['before']['id']),'expected_hash':p['expected_hash']}
            job=g.reserve(topic.strip(),target=target);p['replacement_job_id']=job
            self.images.save(pid,p)
            g.save(job,'기존 글 전체 교체 준비','HOLD',{'topic':topic.strip(),'replacement_target':target})
            return self.resume(pid,generator)
        except Cancelled:raise
        except Exception as exc:
            p['reason']=str(exc);return self.images.save(pid,p)
    def resume(self,pid,generator):
        row,p=self.images.load(pid);self.images.baseline(p)
        if p.get('mode')!='REPLACEMENT':raise ImageHold('전체 교체 작업을 선택하세요.')
        g=Generation(self.store,self.ai,self.adapter.blog_id,self.progress)
        job=p.get('replacement_job_id')
        if type(job) is not int:raise ImageHold('전체 교체 생성 작업 기록 없음: 새 작업 필요')
        try:
            payload=g.load_job(job)['payload'];target=replacement_target(self.store,self.adapter.blog_id,payload)
            if target['proposal_id']!=pid:raise ImageHold('다른 수정안의 생성 작업: 진행 중지')
            from .article_policy import VERSION as ARTICLE_POLICY,strip_auxiliary
            if p.get('replacement_preview_ready') and p.get('article_policy')==ARTICLE_POLICY and text_ready(payload):
                return {'proposal_id':pid,'status':row['status'],**p}
            preserved_choices=deepcopy(p.get('image_choices',{}))
            if p.get('replacement_preview_ready'):
                if any(choice.get('request_id') and not choice.get('receipt') for choice in preserved_choices.values()):
                    raise ImageHold('이전 이미지 업로드 결과 미확정: 수정·복원 결과 확인 후 이어가세요. 재업로드하지 않습니다.')
                from .text_flow import checkpoint
                checkpoint(payload,'이전 시험판 본문·이미지 보존')
                selected=[preserved_choices.get(str(slot),{}).get('candidate') for slot in (1,2)]
                if all(isinstance(c,dict) and c.get('result')=='PASS' for c in selected):
                    payload['image_candidates']=deepcopy(selected)
                for candidate in payload.get('image_candidates',[]):candidate.pop('generation_context',None)
                if payload.get('image_candidates'):payload['preserved_image_candidates']=deepcopy(payload['image_candidates'])
                payload['content']=strip_auxiliary(payload['content'])
                for key in ('deep','fast','replacement_links_ready','text_review_hash','text_review_context','text_review_checked_at'):
                    payload.pop(key,None)
                p.pop('replacement_preview_ready',None)
                for key in ('plan','proposal_hash','replacement_final'):p.pop(key,None)
                g.save(job,'공통 기준으로 기존 본문·이미지 재검사','HOLD',payload)
                self.images.save(pid,p)

            self.progress('저장 본문 검사·보완' if payload.get('content') and not text_ready(payload) else '이미지 단계 준비' if text_ready(payload) else '전체 교체 본문 생성',0,1)
            from .text_flow import continue_saved
            if not text_ready(payload):
                try:
                    if payload.get('content'):continue_saved(g,job)
                    else:
                        g.resume(job)
                        generated=g.load_job(job)['payload']
                        if generated.get('content') and generated.get('deep',{}).get('review') and not text_ready(generated):continue_saved(g,job,use_current_review=True)
                finally:
                    # Generation persists partial results even on cancellation/errors.
                    self.capture(pid,p,g,job)
                payload=g.load_job(job)['payload']
            else:self.capture(pid,p,g,job)
            if not text_ready(payload):raise ImageHold(payload.get('reason','본문 품질 검사 미완료'))
            if not payload.get('replacement_links_ready'):
                from .links import append_verified_candidates
                peers=[dict(r) for r in self.store.db.execute('SELECT post_id,title,content,url,status FROM posts WHERE blog_id=? AND present=1 AND post_id!=?',(self.adapter.blog_id,target['post_id']))]
                self.progress('관련 LIVE 내부링크·공식 근거 배치',0,1)
                payload['content']=append_verified_candidates(self.ai,payload['title'],payload['content'],peers,payload['evidence'],strict=True,record=lambda v:payload.update(reference_bindings=v))
                payload['replacement_links_ready']=True
                g.save(job,'전체 교체 링크 배치','HOLD',payload)
            # Always use the common candidate path: same-context assets reuse
            # without API calls; changed body/links force pixel and text QA.
            try:generate_candidates(g,generator,job,self.cache)
            finally:self.capture(pid,p,g,job)
            payload=g.load_job(job)['payload'];candidates=payload.get('image_candidates',[])
            # Local preview placeholders are never considered public image URLs.
            content=payload['content']
            if Document(content).images:raise ImageHold('신규 본문에 예상하지 않은 이미지: 자동 교체 중지')
            choices={};edits={};seen=set()
            self.cache.mkdir(parents=True,exist_ok=True)
            blocks=[]
            for slot,candidate in enumerate(candidates,1):
                c=dict(candidate)
                if c.get('file') and c.get('info'):
                    data=Path(c['file']).read_bytes();info=inspect_bytes(data)
                    if info['byte_hash']!=c['info']['byte_hash']:raise ImageHold('생성 이미지 파일 변경')
                    cached=self.cache/(info['byte_hash']+'.image');cached.write_bytes(data);c['file']=str(cached)
                    if info['pixel_hash'] in seen:c.update(result='HOLD',reason='두 이미지의 실제 픽셀이 같습니다. 다른 장면으로 재생성하세요.')
                    seen.add(info['pixel_hash'])
                # A rejected image remains visible when pixels exist; it cannot be selected.
                url=f'r3-local:replacement/{pid}/{slot}'
                import html
                block='<figure><img src="'+url+'" alt="'+html.escape(c.get('alt',''),quote=True)+'"><figcaption>그림 '+str(slot)+'. '+html.escape(c.get('caption',''))+'</figcaption></figure>'
                blocks.append(block);edits[str(slot)]=c
                if c.get('result')=='PASS':
                    choice={'candidate':c,'expected_url':url,'mode':'replace'}
                    prior=preserved_choices.get(str(slot),{})
                    receipt=prior.get('receipt')
                    if (isinstance(receipt,dict) and receipt.get('ok') is True
                        and receipt.get('byte_hash')==c.get('info',{}).get('byte_hash')):
                        choice['receipt']=deepcopy(receipt)
                        if prior.get('request_id'):choice['request_id']=prior['request_id']
                    choices[str(slot)]=choice
            if len(blocks)==2:
                from .article_policy import place_figures
                content=place_figures(content,blocks,list(edits.values()))
            for key,c in edits.items():c['edit_mode']='replace';c['target']={'slot':int(key),'url':f'r3-local:replacement/{pid}/{key}','article_hash':digest(content)}
            p.update(article_policy=ARTICLE_POLICY,proposed_content=content,image_choices=choices,image_edit_candidates=edits,replacement_preview_ready=True)
            p['reason']='전체 교체 본문·이미지 후보 준비 · 이미지 확인 후 수정안 최종 검증을 누르세요.' if len(choices)==2 else '전체 교체 본문 보관 · 미통과 이미지 재생성 후 최종 검증 필요'
            self.images.baseline(p)
            return self.images.save(pid,p)
        except Cancelled:
            p['reason']='사용자 중단 · 전체 교체 작업 보관';self.images.save(pid,p);raise
        except Exception as exc:
            p['reason']=str(exc)
            if getattr(exc,'diagnostic',None):p['error_diagnostic']=exc.diagnostic
            return self.images.save(pid,p)
    def capture(self,pid,p,g,job):
        record=g.load_job(job);payload=record['payload']
        p['replacement_stage']=record['stage']
        for key in ('text_versions','text_review_history','text_repair_attempts','image_candidates','fact_search_attempts','image_pipeline','text_repair_run','reference_bindings','article_policy'):
            if payload.get(key):p[key]=deepcopy(payload[key])
        p['generation_text_metrics']=deepcopy(payload.get('fast',{}).get('metrics',{}))
        if payload.get('deep'):p['generation_text_review']=deepcopy(payload['deep'])
        else:p.pop('generation_text_review',None)
        if payload.get('generation_evidence_recovery'):
            p['generation_evidence_recovery']=payload['generation_evidence_recovery']
        if not payload.get('content') and not payload.get('draft_content'):p.pop('proposed_content',None)
        if not payload.get('title'):p.pop('proposed_title',None)
        if payload.get('title'):
            if p.get('proposed_title')!=payload['title']:p.pop('proposed_content',None)
            p['proposed_title']=payload['title']
        if payload.get('content') or payload.get('draft_content'):
            p['proposed_content']=payload.get('content') or payload['draft_content'];p['search_description']=payload.get('search_description','');p['evidence']=payload.get('evidence',{})
        if payload.get('error_diagnostic'):p['error_diagnostic']=payload['error_diagnostic']
        else:p.pop('error_diagnostic',None)
        self.images.save(pid,p)

