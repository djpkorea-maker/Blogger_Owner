"""Compose escaped figures from verified upload receipts; no local paths in HTML."""
import html
import re
from urllib.parse import urlparse
from .gates import Document
from .images import inspect_bytes
from pathlib import Path

class LayoutHold(RuntimeError):
    def __init__(self,message,diagnostic=None):
        super().__init__(message);self.diagnostic=diagnostic

def upload_context(adapter,candidate):
    """Bind future retries to the same destination and exact upload payload."""
    return {'blog_id':str(adapter.blog_id),'bridge_url':getattr(adapter,'url',None),
            'byte_hash':candidate['info']['byte_hash'],'mime':candidate['info']['mime'],
            'file_name':Path(candidate['file']).name}

def recover_upload(adapter,candidate,request_id,index,progress=lambda *a:None,record=lambda event:None):
    """Resume an image only when the guarded journal positively reports absence.

    The guarded Bridge journals before creating a file and serializes writes.
    Reusing the SAME ID also prevents a race with another execution. This rule
    applies only to image uploads, never to post creation, PATCH or rollback.
    A missing/malformed response, RUNNING, or a mismatched DONE must not replay.
    """
    def hold(state,message):
        return LayoutHold(message,{'reason':'UPLOAD_RECONCILE','stage':'이미지 '+str(index)+' 업로드 결과 확인',
            'request_type':'upload_image','server_status':state,'image_slot':index,
            'summary':message,'action':'본문·이미지·작업 기록을 유지하고 업로드 상태를 확인하세요.'})
    actual=inspect_bytes(Path(candidate['file']).read_bytes())
    if candidate.get('result')!='PASS' or actual['byte_hash']!=candidate['info']['byte_hash']:
        raise hold('FILE_CHANGED','검사 이후 이미지 파일 변경: 업로드 복구 중지')
    progress('이미지 '+str(index)+' 이전 업로드 결과 확인',0,1)
    journal=adapter.request_status(request_id)
    if not isinstance(journal,dict):raise hold('INVALID_RESPONSE','이미지 업로드 상태 응답 형식 오류: 재업로드하지 않습니다.')
    state=journal.get('status')
    safe_state=state if state in ('DONE','NOT_FOUND','RUNNING') else 'UNKNOWN'
    record({'server_status':safe_state,'outcome':'CHECKED'})
    if state=='DONE':
        receipt=journal.get('result')
        if (journal.get('action')!='upload_image' or not isinstance(receipt,dict)
            or receipt.get('blogId')!=adapter.blog_id or receipt.get('byte_hash')!=actual['byte_hash']):
            raise hold('DONE_MISMATCH','완료된 이미지 업로드 기록의 작업·블로그·파일 지문 불일치: 재업로드하지 않습니다.')
        figure(candidate,receipt,index)
        receipt['public_pixel_verified']=False
        record({'server_status':'DONE','outcome':'REUSED'})
        return receipt
    if (state=='NOT_FOUND' and journal.get('ok') is True and str(journal.get('blogId'))==str(adapter.blog_id)
        and journal.get('result') is None and journal.get('action') is None):
        import uuid
        try:valid=str(uuid.UUID(request_id))==request_id
        except (ValueError,TypeError,AttributeError):valid=False
        if not valid:raise hold('INVALID_REQUEST','이미지 업로드 요청 번호 손상: 복구 중지')
        record({'server_status':'NOT_FOUND','outcome':'STARTING_SAME_REQUEST'})
        progress('이미지 '+str(index)+' 서버 시작 기록 없음 · 같은 요청 번호로 업로드',0,1)
        receipt=upload_checked(adapter,candidate,request_id)
        figure(candidate,receipt,index)
        record({'server_status':'DONE','outcome':'UPLOADED'})
        return receipt
    raise hold(safe_state,'이전 이미지 업로드 결과 미확정: 재업로드하지 않습니다. 서버 상태: '+safe_state)

def figure(candidate,receipt,index):
    if candidate.get('result')!='PASS':raise LayoutHold('검사 미통과 이미지')
    url=receipt.get('publicImageUrl','')
    if receipt.get('ok') is not True or urlparse(url).scheme!='https' or urlparse(url).hostname!='lh3.googleusercontent.com':raise LayoutHold('검증된 이미지 업로드 결과 필요')
    # Receipt must bind to inspected bytes, not merely point to an arbitrary URL.
    if receipt.get('byte_hash')!=candidate['info']['byte_hash']:raise LayoutHold('업로드 이미지 hash 불일치')
    return '<figure style="margin:24px auto;max-width:1024px"><img src="'+html.escape(url,quote=True)+'" alt="'+html.escape(candidate['alt'],quote=True)+'" style="width:100%;height:auto"><figcaption style="font-size:0.9em;color:#666;margin-top:8px">그림 '+str(index)+'. '+html.escape(candidate['caption'])+'</figcaption></figure>'

def compose(content,candidates,receipts):
    if len(candidates)!=2 or len(receipts)!=2:raise LayoutHold('검증된 이미지 2장 필요')
    if Document(content).images:raise LayoutHold('기존 이미지가 있는 본문은 별도 교체 계획이 필요합니다.')
    from .article_policy import place_figures
    try:output=place_figures(content,[figure(candidates[0],receipts[0],1),figure(candidates[1],receipts[1],2)],candidates)
    except ValueError as exc:raise LayoutHold(str(exc)) from None
    return output

def upload_checked(adapter,candidate,request_id):
    path=Path(candidate['file']);data=path.read_bytes();info=inspect_bytes(data)
    if candidate.get('result')!='PASS' or info['byte_hash']!=candidate['info']['byte_hash']:raise LayoutHold('검사 이후 이미지 변경: 업로드 중지')
    receipt=adapter.upload_image(data,info['mime'],path.name,request_id)
    if receipt.get('byte_hash') is not None and receipt['byte_hash']!=info['byte_hash']:raise LayoutHold('서버 업로드 이미지 hash 불일치')
    receipt['byte_hash']=info['byte_hash']
    # Public serving may resize the image. Fetch/pixel recheck remains mandatory
    # before granting whole-article PASS or publishing.
    receipt['public_pixel_verified']=False
    return receipt

def reconcile_uploads(generation,adapter,job_id):
    payload=generation.load_job(job_id)['payload']
    images=payload.get('image_candidates',[]);requests=payload.get('upload_requests',[]);receipts=payload.get('upload_receipts',[])
    if len(images)!=2 or not 1<=len(requests)<=2 or len(receipts)>len(requests):raise LayoutHold('확인할 이미지 업로드 기록 없음 또는 기록 불일치')
    for index,request in enumerate(requests):
        if index<len(receipts):continue
        candidate=images[index]
        if candidate.get('result')!='PASS' or candidate['info']['byte_hash']!=request['byte_hash']:raise LayoutHold('검사 이미지와 업로드 요청 불일치')
        actual=inspect_bytes(Path(candidate['file']).read_bytes())
        if actual['byte_hash']!=request['byte_hash']:raise LayoutHold('검사 이후 이미지 파일 변경')
        journal=adapter.request_status(request['id']);result=journal.get('result') or {}
        if journal.get('status')!='DONE' or journal.get('action')!='upload_image' or result.get('blogId')!=adapter.blog_id or result.get('byte_hash')!=request['byte_hash']:raise LayoutHold('서버 업로드 결과 미확정 또는 이미지 hash 불일치')
        figure(candidate,result,index+1) # Validate URL and receipt hash before saving.
        result['public_pixel_verified']=False;receipts.append(result);request['status']='VERIFIED'
        payload['upload_receipts']=receipts;generation.save(job_id,'이미지 업로드 결과 확인','HOLD',payload)
    if len(receipts)==2:return generation.compose_uploaded(job_id,receipts)
    return {'job_id':job_id,'status':'HOLD','reason':'확인된 이미지 업로드 기록을 저장했습니다. 나머지 이미지 업로드가 필요합니다.'}
