"""Configurable Gemini image generation, bounded QA retries, permanent attempts."""
import base64
import io
import json
import os
from pathlib import Path
from PIL import Image
from .ai import Gemini,AIError,output_blocks
from .images import ImageQA,ImageHold,inspect_bytes
from .sync import now,digest

class Generator(Gemini):
    @classmethod
    def from_environment(cls):return cls(os.environ.get('R3_GEMINI_KEY',''),os.environ.get('R3_IMAGE_MODEL',''))
    def image(self,prompt):
        raw=self.transport({'model':self.model,'input':prompt,'store':False,'response_format':{'type':'image','mime_type':'image/jpeg','aspect_ratio':'16:9','image_size':'1K'}})
        blocks=output_blocks(raw)
        images=[b for b in blocks if b.get('type')=='image' and b.get('data')]
        if len(images)!=1:raise AIError('이미지 생성 결과 없음 또는 다중 이미지 응답')
        try:data=base64.b64decode(images[0]['data'],validate=True)
        except (ValueError,TypeError):raise AIError('이미지 응답 손상') from None
        # Verify before decode/resize; standardizes ONLY newly generated assets.
        inspect_bytes(data)
        with Image.open(io.BytesIO(data)) as im:
            im=im.convert('RGB').resize((1024,576),Image.Resampling.LANCZOS)
            for quality in (90,82,74,65):
                out=io.BytesIO();im.save(out,format='JPEG',quality=quality,optimize=True)
                result=out.getvalue()
                if len(result)<=500*1024:return result
        raise ImageHold('이미지 500KB 제한 충족 실패')

def generate_candidates(generation,generator,job_id,directory):
    payload=generation.load_job(job_id)['payload']
    if not payload.get('content') or not payload.get('title'):raise ImageHold('본문 작성 완료 후 이미지 생성 가능')
    from .text_flow import ready
    if not ready(payload):
        raise ImageHold('사실·안전·품질 검사 완료 후 이미지 생성 가능: 본문 검사·보완 기록을 확인하세요.')
    directory=Path(directory)/('job_'+str(job_id));directory.mkdir(parents=True,exist_ok=True)
    db=generation.store.db
    db.execute('CREATE TABLE IF NOT EXISTS image_generation_attempts(id INTEGER PRIMARY KEY,job_id INTEGER,slot INTEGER,attempt INTEGER,created_at TEXT,status TEXT,payload TEXT)');db.commit()
    context=digest({'version':78,'title':payload['title'],'content':payload['content'],
                    'image_model':generator.model,'qa_model':generation.ai.model})
    previous=payload.get('image_candidates',[]) or payload.get('preserved_image_candidates',[])
    payload.setdefault('image_pipeline',{'status':'PREPARING','generation_started':any(c.get('generation_context')==context for c in previous),'stage':'이미지 단계 준비'})
    scenes=payload.get('image_scene_plan',{})
    prompts=scenes.get('prompts') if scenes.get('context')==context else None
    if not isinstance(prompts,list) or len(prompts)!=2 or any(not isinstance(p,str) or not p.strip() for p in prompts):
        payload['image_pipeline']={'status':'PLANNING','generation_started':bool(payload.get('image_pipeline',{}).get('generation_started')),'stage':'이미지 2장 장면 계획'}
        generation.save(job_id,'이미지 2장 장면 계획','RUNNING',payload)
        plan=generation.ai.object('본문에 맞는 서로 다른 단일 장면 이미지 2개를 계획하세요. prompts:[문자열,문자열], section_indices:[각 이미지와 직접 관련된 본문 H2 구역 번호 1부터, 서로 다른 번호]. 참고 자료·관련 글 구역은 번호에 포함하지 마세요. 실제 안전 점검·사용 조건과 연결되는 장면을 고르세요. 붉은 표시등이나 장치 모습은 고장 원인을 증명하지 않습니다. 동양적 생활환경과 장비를 우선합니다. 글에 없는 장비를 넣지 마세요. 콜라주·분할 화면·글자 삽입 금지. 정확한 회로도나 치수 도면을 그림으로 만들지 마세요.\n'+json.dumps({'title':payload['title'],'content':payload['content']},ensure_ascii=False))
        if not isinstance(plan,dict):raise ImageHold('이미지 장면 계획 응답 형식 오류')
        prompts=plan.get('prompts')
        placements=plan.get('section_indices')
        if placements is not None:
            from .article_policy import sections
            count=len(sections(payload['content'])[1])
            if not isinstance(placements,list) or len(placements)!=2 or any(type(i) is not int or not 1<=i<=count for i in placements) or len(set(placements))!=2:raise ImageHold('이미지 장면의 본문 구역 번호 확인 필요')
        scenes={'section_indices':placements}
    if not isinstance(prompts,list) or len(prompts)!=2 or any(not isinstance(p,str) or not p.strip() for p in prompts):raise ImageHold('이미지 장면 계획 오류')
    payload['image_scene_plan']={'context':context,'prompts':prompts,'section_indices':scenes.get('section_indices')}
    results=[]
    def save_result(stage):
        payload['image_candidates']=list(results)
        for key in ('composed_content','linked_content','upload_receipts','upload_requests','final','final_fact_article_hash'):payload.pop(key,None)
        generation.save(job_id,stage,'HOLD',payload)
    for slot,prompt in enumerate(prompts,1):
        old=previous[slot-1] if len(previous)>=slot else {}
        if old.get('result')=='PASS' and old.get('generation_context')==context:
            try:
                info=inspect_bytes(Path(old['file']).read_bytes())
                if info['byte_hash']==old['info']['byte_hash'] and info['pixel_hash']==old['info']['pixel_hash'] and all(r.get('info',{}).get('pixel_hash')!=info['pixel_hash'] for r in results):
                    results.append(old);generation.progress('통과 이미지 '+str(slot)+' 재사용',slot,2)
                    save_result('이미지 '+str(slot)+' 통과 후보 재사용');continue
            except (OSError,KeyError,ImageHold):pass
        # Changed article: keep checked bytes and re-run pixel/ALT/caption QA
        # against this exact body before deciding whether new generation is needed.
        if old.get('result')=='PASS' and old.get('file') and old.get('info'):
            try:
                info=inspect_bytes(Path(old['file']).read_bytes())
                if info['byte_hash']!=old['info']['byte_hash'] or info['pixel_hash']!=old['info']['pixel_hash']:raise ImageHold('보존 이미지 파일 변경')
                generation.progress('보존 이미지 '+str(slot)+' 픽셀·ALT·그림 설명 재검사',0,1)
                checked,_=ImageQA(generation.store,generation.ai).check(old['file'],payload['title'],payload['content'],generation.blog_id,'job:'+str(job_id),force=True)
                if checked.get('error_diagnostic'):raise AIError(checked.get('reason','이미지 재검사 오류'),checked['error_diagnostic'])
                if checked.get('result')=='PASS' and all(r.get('info',{}).get('pixel_hash')!=checked.get('info',{}).get('pixel_hash') for r in results):
                    checked['generation_context']=context;checked['reused_after_body_review']=True
                    placement=payload['image_scene_plan'].get('section_indices')
                    if placement:checked['placement_section']=placement[slot-1]
                    results.append(checked);save_result('보존 이미지 '+str(slot)+' 재검사 통과');continue
            except AIError as exc:
                payload['image_pipeline'].update(status='HOLD',stage='보존 이미지 '+str(slot)+' 재검사 연결 오류')
                payload['error_diagnostic']={**exc.diagnostic,'stage':payload['image_pipeline']['stage']}
                payload['reason']=str(exc)
                generation.save(job_id,payload['image_pipeline']['stage'],'HOLD',payload)
                raise
            except (OSError,KeyError,ImageHold):pass
        result=None
        for attempt in range(1,4):
            generation.progress('이미지 '+str(slot)+' 생성·픽셀·ALT·그림 설명',attempt,3)
            with db:
                attempt_id=db.execute('INSERT INTO image_generation_attempts(job_id,slot,attempt,created_at,status,payload) VALUES(?,?,?,?,?,?)',(job_id,slot,attempt,now(),'RUNNING',json.dumps({'prompt':prompt,'model':generator.model},ensure_ascii=False))).lastrowid
            terminal=None
            try:
                payload['image_pipeline']={'status':'GENERATING','generation_started':True,'slot':slot,'attempt':attempt,'stage':'이미지 '+str(slot)+' 생성 API 응답 대기'}
                generation.save(job_id,payload['image_pipeline']['stage'],'RUNNING',payload)
                data=generator.image(prompt+'\nSingle coherent scene. 16:9. No collage, labels, captions or text overlays. East Asian household setting. Avoid unsupported technical details.')
                path=directory/f'image_{slot}_attempt_{attempt_id}.jpg';path.write_bytes(data)
                payload['image_pipeline'].update(status='CHECKING',stage='이미지 '+str(slot)+' 실제 픽셀·ALT·그림 설명 검사')
                generation.save(job_id,payload['image_pipeline']['stage'],'RUNNING',payload)
                generation.progress('이미지 '+str(slot)+' 실제 픽셀·ALT·그림 설명 검사',0,1)
                result,_=ImageQA(generation.store,generation.ai).check(path,payload['title'],payload['content'],generation.blog_id,'job:'+str(job_id))
                if result.get('error_diagnostic'):terminal=AIError(result.get('reason','이미지 AI 연결 오류'),result['error_diagnostic'])
            except (AIError,ImageHold,OSError) as exc:
                result={'result':'HOLD','reason':str(exc)}
                if isinstance(exc,AIError) and exc.diagnostic:
                    result['error_diagnostic']=exc.diagnostic;terminal=exc
            result['generation_context']=context
            placement=payload['image_scene_plan'].get('section_indices')
            if placement:result['placement_section']=placement[slot-1]
            if result.get('result')=='PASS' and any(r.get('info',{}).get('pixel_hash')==result.get('info',{}).get('pixel_hash') for r in results):
                result.update(result='HOLD',reason='두 이미지의 실제 픽셀이 같습니다. 다른 본문 장면으로 재생성하세요.')
            status=result['result']
            payload['image_pipeline'].update(status=status,stage='이미지 '+str(slot)+' 생성·QA '+status)
            with db:db.execute('UPDATE image_generation_attempts SET status=?,payload=? WHERE id=?',(status,json.dumps(result,ensure_ascii=False),attempt_id))
            payload['image_candidates']=results+[result]
            payload['reason']='이미지 '+str(slot)+' · '+('픽셀·ALT·그림 설명 검사 통과' if status=='PASS' else result.get('reason','후보 보류'))
            generation.save(job_id,'이미지 '+str(slot)+' 생성·QA','HOLD',payload)
            if terminal:
                payload['error_diagnostic']={**terminal.diagnostic,'stage':'이미지 '+str(slot)+' 생성·QA'}
                generation.save(job_id,'이미지 '+str(slot)+' 연결 오류','HOLD',payload)
                raise terminal
            if status=='PASS':break
        results.append(result);save_result('이미지 '+str(slot)+' 후보 기록 보관')
    payload.pop('error_diagnostic',None)
    payload['image_pipeline'].update(status='READY' if all(r['result']=='PASS' for r in results) else 'HOLD',stage='이미지 2장·ALT·그림 설명 검사 종료')
    payload['reason']='이미지 2장 생성·QA 완료. 업로드 대기' if all(r['result']=='PASS' for r in results) else '이미지 생성·QA 보강 후에도 보류'
    save_result('이미지 자동 생성')
    return {'job_id':job_id,'status':'HOLD','reason':payload['reason'],'images':results}
