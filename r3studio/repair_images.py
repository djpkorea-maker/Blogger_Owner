"""Persistent local image choices; whole-proposal validation precedes Blogger PATCH."""
import html,json,uuid
from pathlib import Path
from .sync import digest,post_hash,now
from .images import ImageQA,ImageHold,inspect_bytes,public_image_bytes
from .gates import Document,fast_check
from .evidence import collect_cached
from .deep import evaluate
from .links import check_links
from .images import check_public_images
from .apply import Apply
from .captions import Tree,Node,VOID
from .layout import figure,upload_checked,recover_upload,upload_context
from .tasks import Cancelled

def render(node):
    if isinstance(node,str):return html.escape(node,quote=False)
    inner=''.join(render(c) for c in node.children)
    if not node.tag:return inner
    attrs=''.join(' '+k+('="'+html.escape(str(v),quote=True)+'"' if v is not None else '') for k,v in node.attrs.items())
    return '<'+node.tag+attrs+'>'+('' if node.tag in VOID else inner+'</'+node.tag+'>')

def replace_slot(content,slot,expected_url,candidate,receipt):
    """Replace only an unambiguous image block; preserve all other article content."""
    root=Tree(content).root;images=[n for n in root.nodes() if n.tag=='img']
    if type(slot) is not int or not 1<=slot<=len(images):raise ImageHold('이미지 번호 확인 필요')
    image=images[slot-1]
    if image.attrs.get('src')!=expected_url:raise ImageHold('교체 대상 이미지 변경: 적용 중지')
    block=image
    while block.parent and block.tag not in ('figure','div','p'):block=block.parent
    if block.parent is None or sum(n.tag=='img' for n in block.nodes())!=1:raise ImageHold('이미지별 교체 위치 불확실')
    if block.tag=='figure':
        if sum(n.tag=='figcaption' for n in block.nodes())>1:raise ImageHold('그림 설명 중복: 교체 위치 확인 필요')
        def outside_caption(node):
            if isinstance(node,str):return node
            return '' if node.tag=='figcaption' else ''.join(outside_caption(c) for c in node.children)
        if outside_caption(block).strip():raise ImageHold('그림 구역에 일반 본문이 있어 자동 교체 중지')
    elif block.tag=='div' and 'separator' in block.attrs.get('class','').split():
        if block.text().strip():raise ImageHold('이미지 구역에 본문이 있어 자동 교체 중지')
        siblings=block.parent.children;idx=siblings.index(block)+1
        while idx<len(siblings) and isinstance(siblings[idx],str) and not siblings[idx].strip():idx+=1
        if idx<len(siblings) and isinstance(siblings[idx],Node) and 'abs-v23-caption' in siblings[idx].attrs.get('class','').split():
            if any(n.tag=='img' for n in siblings[idx].nodes()):raise ImageHold('설명 구역에 다른 이미지가 있어 교체 중지')
            siblings.pop(idx)
    elif block.tag=='p':
        import re
        text=' '.join(block.text().split())
        if len(text)>250 or text and not re.match(r'^그림\s*'+str(slot)+r'\s*[.：:]\s*',text):raise ImageHold('이미지와 일반 본문이 같은 문단: 자동 교체 중지')
    else:raise ImageHold('명확한 이미지 블록 필요')
    replacement=Tree(figure(candidate,receipt,slot)).root.children[0]
    siblings=block.parent.children;siblings[siblings.index(block)]=replacement;replacement.parent=block.parent
    return render(root)

class RepairImages:
    def __init__(self,store,adapter,ai,cache_dir,progress=lambda *a:None):
        self.store,self.adapter,self.ai=store,adapter,ai;self.cache=Path(cache_dir);self.progress=progress
    def load(self,pid):
        row=self.store.db.execute('SELECT * FROM repair_proposals WHERE id=? AND blog_id=?',(pid,self.adapter.blog_id)).fetchone()
        if not row or row['status'] not in ('HOLD','PASS'):raise ImageHold('편집 가능한 수정안을 선택하세요.')
        try:
            p=json.loads(row['payload']);before=p['before']
            if p['expected_hash']!=post_hash(before) or str(before['id'])!=row['post_id']:raise ValueError()
        except (ValueError,KeyError,TypeError):raise ImageHold('수정안 기록 손상: 이미지 변경 중지') from None
        return row,p
    def save(self,pid,p,status='HOLD',invalidate=True):
        if invalidate:
            for key in ('plan','proposal_hash','corpus_hash','deep','images','links'):p.pop(key,None)
        with self.store.db:self.store.db.execute('UPDATE repair_proposals SET status=?,created_at=?,payload=? WHERE id=? AND blog_id=?',(status,now(),json.dumps(p,ensure_ascii=False),pid,self.adapter.blog_id))
        return {'proposal_id':pid,'status':status,**p}
    def check_binding(self,candidate,slot,url,content):
        binding=candidate.get('target')
        if binding and binding!={'slot':slot,'url':url,'article_hash':digest(content)}:
            raise ImageHold('이미지 번호·대상 변경: 후보를 다시 검사하세요.')
    def baseline(self,p):
        current=self.adapter.get_post(str(p['before']['id']))
        if post_hash(current)!=p['expected_hash'] or current['updated']!=p['before']['updated'] or current.get('url','')!=p['before'].get('url','') or current.get('published')!=p['before'].get('published'):raise ImageHold('LIVE 변경 감지: 새 수정안 필요')
    def operate(self,pid,action,slot=1,path=None,generator=None,download=public_image_bytes):
        row,p=self.load(pid)
        content=p.get('proposed_content') or p.get('plan',{}).get('proposal',{}).get('content','')
        if not content:raise ImageHold('본문 수정안을 먼저 만드세요.')
        p['proposed_content']=content
        images=Document(content).images
        if type(slot) is not int or not 1<=slot<=len(images):raise ImageHold('이미지 번호 확인 필요')
        key=str(slot);choices=p.setdefault('image_choices',{});candidates=p.setdefault('image_edit_candidates',{})
        if action=='cancel':
            choices.pop(key,None);candidates.pop(key,None);p['reason']='새 이미지 후보 선택 취소 · 새 후보를 검사·선택해야 전체 교체할 수 있습니다.' if p.get('mode')=='REPLACEMENT' else '이미지 후보 취소 · 기존 이미지 유지 · 최종 재검증 필요'
            return self.save(pid,p)
        if action=='choose':
            candidate=candidates.get(key,{})
            self.check_binding(candidate,slot,images[slot-1]['src'],content)
            if candidate.get('result')!='PASS':raise ImageHold('본문 관련성·픽셀·ALT 검증 PASS 후보만 선택할 수 있습니다.')
            if inspect_bytes(Path(candidate['file']).read_bytes())['byte_hash']!=candidate['info']['byte_hash']:raise ImageHold('선택 후보 파일 변경')
            choices[key]={'candidate':candidate,'expected_url':images[slot-1]['src'],'mode':candidate.get('edit_mode','replace')}
            p['reason']='이미지 후보 선택 완료 · 전체 수정안 최종 검증 필요'
            return self.save(pid,p)
        self.baseline(p);self.cache.mkdir(parents=True,exist_ok=True)
        mode='replace'
        if action=='generate':
            if generator is None:raise ImageHold('이미지 생성 모델 설정 필요')
            self.progress('본문 관련 이미지 장면 계획',0,1)
            plan=self.ai.object('이 글과 직접 관련된 이미지 한 장의 장면을 계획하세요. prompt:문자열. 글에 없는 부품·브랜드·원리를 만들지 마세요. 다른 이미지와 같은 장면을 반복하지 마세요. 선택한 이미지 번호에 맞는 서로 다른 관련 장면을 사용하세요. 실제 생활 장면, 동양적 환경, 하나의 장면, 16:9. 글자·콜라주·정밀 회로도 금지.\n'+json.dumps({'title':p.get('proposed_title',p['before']['title']),'article':content,'slot':slot,'other_image_scenes':[{'slot':k,'scene':v.get('review',{}).get('observed',''),'alt':v.get('alt','')} for k,v in candidates.items() if k!=key]},ensure_ascii=False))
            prompt=plan.get('prompt')
            if not isinstance(prompt,str) or not prompt.strip():raise ImageHold('이미지 장면 계획 응답 오류')
            self.progress('관련 이미지 후보 생성',0,1)
            data=generator.image(prompt+'\nSingle coherent scene, no text, no collage, 16:9.')
        elif action=='import':
            source=Path(path)
            if source.stat().st_size>2*1024*1024:raise ImageHold('이미지 최대 2MB')
            data=source.read_bytes()
        elif action=='alt':
            mode='text';selected=choices.get(key)
            if selected:
                self.check_binding(selected['candidate'],slot,images[slot-1]['src'],content)
                data=Path(selected['candidate']['file']).read_bytes();mode=selected['mode']
                if inspect_bytes(data)['byte_hash']!=selected['candidate']['info']['byte_hash']:raise ImageHold('선택 이미지 파일 변경')
            else:data=download(images[slot-1]['src'])
        else:raise ImageHold('알 수 없는 이미지 작업')
        info=inspect_bytes(data);file=self.cache/(info['byte_hash']+'.image');file.write_bytes(data)
        self.progress('후보 실제 픽셀·본문 관련성·ALT·설명 검사',0,1)
        candidate,_=ImageQA(self.store,self.ai).check(file,p.get('proposed_title',p['before']['title']),content,self.adapter.blog_id,'repair:'+str(pid),force=action=='alt')
        candidate['edit_mode']=mode
        candidate['target']={'slot':slot,'url':images[slot-1]['src'],'article_hash':digest(content)}
        candidate['checked_pixel_hash']=info['pixel_hash']
        if action in ('generate','import') and any(v.get('info',{}).get('pixel_hash')==info['pixel_hash'] for k,v in candidates.items() if k!=key):
            candidate['result']='HOLD';candidate['reason']='다른 번호의 후보와 실제 픽셀이 같습니다. 다른 관련 장면으로 재생성하세요.'
        candidates[key]=candidate
        p['reason']='후보 검증 '+candidate['result']+' · 이 후보로 교체를 누르기 전에는 선택 이미지가 바뀌지 않습니다.'
        return self.save(pid,p)
    def repair_evidence(self,pid):
        from .final_text_repair import repair
        return repair(self,pid)
    def validate(self,pid,download=public_image_bytes,fetch=None):
        from dataclasses import asdict
        from .google import public_fetch
        from .finalize import corpus_hash
        row,p=self.load(pid);content=p.get('proposed_content','');self.baseline(p)
        title=p.get('proposed_title',p['before']['title']);base_url=p.get('site_url') or p['before'].get('url','')
        self.save(pid,p) # Revoke old PASS before any external call.
        p.pop('error_diagnostic',None)
        p['validation_stage']='이미지 업로드 결과 확인'
        self.save(pid,p)
        try:
            if p.get('mode')=='REPLACEMENT':
                import re
                if re.search(r'<\s*(?:script|iframe|object|embed|form)\b|\bon[a-z]+\s*=|javascript\s*:',content,re.I):raise ImageHold('새 본문에 실행 코드 또는 외부 삽입 구역이 있어 전체 교체 중지')
            if p.get('mode')=='REPLACEMENT' and set(p.get('image_choices',{}))!={'1','2'}:raise ImageHold('전체 교체는 검증된 새 이미지 2장을 모두 선택해야 합니다.')
            for key,choice in p.get('image_choices',{}).items():
                candidate=choice['candidate'];slot=int(key)
                self.check_binding(candidate,slot,choice['expected_url'],p.get('proposed_content',''))
                info=inspect_bytes(Path(candidate['file']).read_bytes())
                if candidate.get('result')!='PASS' or info['byte_hash']!=candidate['info']['byte_hash']:raise ImageHold('이미지 후보 변경 또는 미통과')
                if choice['mode']=='text':receipt={'ok':True,'publicImageUrl':choice['expected_url'],'byte_hash':info['byte_hash']}
                else:
                    receipt=choice.get('receipt')
                    if not receipt:
                        context=upload_context(self.adapter,candidate)
                        if choice.get('upload_context') is not None and choice['upload_context']!=context:
                            raise ImageHold('이미지 업로드 대상·파일 기록 변경: 기존 요청을 재사용하지 않습니다.')
                        choice['upload_context']=context
                        if choice.get('request_id'):
                            def record_upload(event):
                                choice['upload_recovery']=dict(event,image_slot=slot)
                                p.setdefault('upload_recovery_history',[]).append(dict(event,image_slot=slot,at=now()))
                                p['upload_recovery_history']=p['upload_recovery_history'][-20:]
                                self.save(pid,p)
                            self.save(pid,p)
                            receipt=recover_upload(self.adapter,candidate,choice['request_id'],slot,self.progress,record_upload)
                        else:
                            choice['request_id']=str(uuid.uuid4());self.save(pid,p)
                            self.progress('이미지 '+str(slot)+' 공개 업로드',0,1)
                            receipt=upload_checked(self.adapter,candidate,choice['request_id'])
                        figure(candidate,receipt,slot);choice['receipt']=receipt;self.save(pid,p)
                content=replace_slot(content,slot,choice['expected_url'],candidate,receipt)
            p['validation_content']=content
            self.progress('수정된 본문 근거 최종 재검증',0,1)
            p['validation_stage']='수정된 본문 근거 최종 재검증'
            self.save(pid,p)
            def record_evidence(event):
                p.setdefault('final_evidence_attempts',[]).append(dict(event,at=now(),article_hash=digest(content)))
                p['final_evidence_attempts']=p['final_evidence_attempts'][-20:]
                self.save(pid,p)
            before=p['before'];pack=collect_cached(self.store,self.ai,title,title,self.adapter.blog_id+':image-repair:'+str(pid)+':'+digest(content),self.progress,article=content,recheck_originals=True,record_review=record_evidence)
            corpus=[dict(r) for r in self.store.db.execute('SELECT post_id,title,content,url,status FROM posts WHERE blog_id=? AND present=1',(self.adapter.blog_id,))]
            peers=[r for r in corpus if r['status']=='LIVE' and r['post_id']!=str(before['id'])]
            from .article_policy import generated_fast,VERSION as ARTICLE_POLICY
            checker=generated_fast if p.get('mode')=='REPLACEMENT' else fast_check
            fast=asdict(checker(dict(before,title=title,content=content,url=base_url),peers))
            if fast['issues']:raise ImageHold('수정안 형식 검사 보류: '+' / '.join(fast['issues']))
            p['validation_stage']='본문 사실·안전·품질 검사'
            self.save(pid,p)
            self.progress('본문 사실·안전·품질 검사',0,1)
            from .fact_search import collect
            def record_fact(attempts):
                p['fact_search_attempts']=attempts
                self.save(pid,p)
            audit=collect(self.ai,title,content,pack,self.progress,record_fact,
                stage='수정안 최종 독립 Fact 검색',image_generation_started=p.get('mode')=='REPLACEMENT')
            deep=evaluate(self.ai,dict(before,title=title,content=content,independent_fact_search=audit),pack,fast)
            if not deep.get('text_verified'):
                from .text_flow import diagnosis
                from .evidence import EvidenceHold
                problem=diagnosis({'title':title,'content':content,'deep':deep,'fast':fast})
                p['final_deep_result']=deep
                raise EvidenceHold(problem['summary'],diagnostic=problem)
            p['validation_stage']='공개 이미지 최종 관련성·ALT 검사'
            self.save(pid,p)
            self.progress('공개 이미지 최종 관련성·ALT 검사',0,1)
            checked=check_public_images(self.store,self.ai,title,content,self.cache,self.adapter.blog_id,str(before['id']),download)
            if len(checked)!=2:raise ImageHold('검증된 이미지 2장 필요')
            if p.get('mode')=='REPLACEMENT':
                from .finalize import decide
                final_payload={'title':title,'composed_content':content,'search_description':p.get('search_description',''),'labels':before.get('labels',[]),'evidence':pack,'independent_fact_search':audit,'final_fact_article_hash':digest({'title':title,'content':content}),'reference_bindings':p.get('reference_bindings')}
                p['replacement_final']=decide(self.ai,final_payload,[r for r in corpus if r['post_id']!=str(before['id'])],base_url,checked,fetch or public_fetch)
            p['validation_stage']='링크·최종 적용 조건 검사'
            self.save(pid,p)
            links=check_links(content,base_url,corpus,pack,fetch or public_fetch)
            self.baseline(p);plan=Apply(self.store,self.adapter).prepare(str(before['id']),title,content,before.get('labels',[]))
            if plan['expected_hash']!=p['expected_hash'] or plan['expected_updated']!=before['updated'] or plan['expected_url']!=before.get('url',''):raise ImageHold('검증 중 LIVE 변경: 적용 중지')
            p.update(plan=plan,proposal_hash=digest(plan['proposal']),corpus_hash=corpus_hash(corpus),evidence=pack,deep=deep,images=checked,links=links,reason='수정안 전체 검증 통과 · 검토 후 적용 가능')
            p.pop('error_diagnostic',None)
            p['validation_stage']='수정안 전체 검증 완료'
            return self.save(pid,p,'PASS',invalidate=False)
        except Cancelled:raise
        except Exception as exc:
            p['reason']=str(exc)
            if getattr(exc,'diagnostic',None):p['error_diagnostic']=exc.diagnostic
            partial=getattr(exc,'partial_pack',None)
            if (isinstance(partial,dict) and getattr(exc,'diagnostic',{}).get('reason') in ('EVIDENCE_ORIGINALS_INCOMPLETE','EVIDENCE_INCOMPLETE')):
                from copy import deepcopy
                p['final_evidence_pack']=deepcopy(partial)
                p['final_evidence_for']=digest({'title':title,'content':p.get('proposed_content','')})
            return self.save(pid,p)
