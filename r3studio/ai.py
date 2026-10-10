"""Gemini Interactions REST client; explicit model, no credentials in artifacts."""
import json
import os
import re
import urllib.request
import urllib.error
import socket
import time

class AIError(RuntimeError):
    def __init__(self,message,diagnostic=None):
        super().__init__(message)
        self.diagnostic=diagnostic

ERROR_GUIDANCE={
    400:('요청 형식 또는 모델 지원 기능 오류','모델명과 검색·JSON 요청 형식을 확인하세요.'),
    401:('API 인증 실패','연결 설정에 저장한 API 키를 확인하세요.'),
    402:('결제 또는 크레딧 문제','이 API 키가 속한 프로젝트의 결제 상태를 확인하세요.'),
    403:('API 사용 권한 또는 키 제한','API 키의 프로젝트·서비스 권한·키 제한을 확인하세요.'),
    404:('모델 또는 API 경로를 찾지 못함','설정한 모델명과 해당 API 지원 여부를 확인하세요.'),
    429:('요청 횟수 또는 사용량 제한','잔액 부족으로 단정할 수 없습니다. 프로젝트의 요청·토큰 한도를 확인하세요.'),
    500:('AI 서버 내부 오류','잠시 후 한 글만 다시 검사하세요.'),
    503:('AI 서버 일시 과부하','잠시 후 한 글만 다시 검사하세요.'),
    504:('AI 서버 응답 지연','잠시 후 한 글만 다시 검사하세요.')}

def connection_error(code,model,body=b'',retry_after=None):
    # Store only classified information; never persist raw server messages or requests.
    title,action=ERROR_GUIDANCE.get(code,('AI 요청 실패','오류 코드와 모델 설정을 확인하세요.'))
    reason=''
    try:
        raw=json.loads(body);error=raw.get('error',{})
        status=error.get('status') or error.get('type')
        if status in ('INVALID_ARGUMENT','UNAUTHENTICATED','PERMISSION_DENIED','NOT_FOUND','RESOURCE_EXHAUSTED','INTERNAL','UNAVAILABLE','DEADLINE_EXCEEDED','invalid_request','permission_denied','resource_exhausted','service_unavailable'):
            reason=status
        message=str(error.get('message','')).lower()
        if 'api key' in message and any(w in message for w in ('invalid','expired','not valid')):
            title,action='API 키가 유효하지 않음','연결 설정의 API 키와 키 사용 제한을 확인하세요.'
            reason='INVALID_API_KEY'
    except (ValueError,TypeError,AttributeError):pass
    diagnostic={'http_status':code,'reason':reason,'model':model,'summary':title,'action':action}
    if retry_after and str(retry_after).isdigit():diagnostic['retry_after_seconds']=min(int(retry_after),86400)
    text=f'AI 연결 실패 · HTTP {code} · {title}\n모델: {model}\n'+action
    if reason:text+='\n오류 분류: '+reason
    if 'retry_after_seconds' in diagnostic:text+=f"\n서버 재시도 안내: {diagnostic['retry_after_seconds']}초 이후"
    return AIError(text,diagnostic)


def output_blocks(raw):
    if not isinstance(raw,dict):raise AIError('AI 응답 형식 오류')
    if raw.get('status') is not None and raw['status']!='completed':raise AIError('AI 응답 미완료: 결과를 통과 처리하지 않습니다.')
    blocks=[]
    steps=raw.get('steps',[])
    if not isinstance(steps,list):raise AIError('AI 응답 단계 형식 오류')
    for step in steps:
        if not isinstance(step,dict):raise AIError('AI 응답 단계 형식 오류')
        if step.get('type')=='model_output':
            content=step.get('content',[])
            if not isinstance(content,list):raise AIError('AI 응답 본문 형식 오류')
            blocks.extend(content)
    if not blocks:blocks=raw.get('outputs',[])
    if not isinstance(blocks,list) or any(not isinstance(b,dict) for b in blocks):raise AIError('AI 응답 본문 형식 오류')
    return blocks

class Gemini:
    REQUEST_TIMEOUT_SECONDS=120
    def __init__(self,key,model,transport=None):
        if not key or not re.fullmatch(r'[A-Za-z0-9._-]+',model):
            raise AIError('Gemini API 키와 모델명을 설정하세요.')
        self.key,self.model,self.transport=key,model,transport or self._http
        self.request_timeout_seconds=self.REQUEST_TIMEOUT_SECONDS
    @classmethod
    def from_environment(cls):
        return cls(os.environ.get('R3_GEMINI_KEY',''),os.environ.get('R3_GEMINI_MODEL',''))
    def _http(self,payload):
        req=urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/interactions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','x-goog-api-key':self.key},method='POST')
        try:
            with urllib.request.urlopen(req,timeout=self.request_timeout_seconds) as res:
                data=res.read(8*1024*1024+1)
                if len(data)>8*1024*1024: raise AIError('AI 응답 크기 초과')
                return json.loads(data)
        except urllib.error.HTTPError as exc:
            try:body=exc.read(65536)
            except OSError:body=b''
            raise connection_error(exc.code,self.model,body,exc.headers.get('Retry-After') if exc.headers else None) from None
        except (TimeoutError,socket.timeout):
            raise AIError('AI 응답 시간 초과: 서버 응답을 기다리다 중단했습니다. 잠시 후 한 글만 재검사하세요.',{'reason':'TIMEOUT','model':self.model,'summary':'응답 시간 초과','action':'잠시 후 한 글만 재검사하세요.'}) from None
        except urllib.error.URLError as exc:
            timeout=isinstance(exc.reason,(TimeoutError,socket.timeout))
            reason='TIMEOUT' if timeout else 'NETWORK'
            raise AIError('AI 연결 실패: '+('응답 시간 초과' if timeout else '인터넷·DNS·보안 연결 확인 필요'),{'reason':reason,'model':self.model,'summary':'응답 시간 초과' if timeout else '네트워크 연결 실패','action':'인터넷 연결을 확인하고 잠시 후 한 글만 재검사하세요.'}) from None
        except OSError:
            raise AIError('AI 네트워크 연결 실패: 인터넷 연결을 확인하세요.',{'reason':'NETWORK','model':self.model,'summary':'네트워크 연결 실패','action':'인터넷 연결을 확인하세요.'}) from None
        except ValueError:
            raise AIError('AI 서버 응답 형식 오류: 정상 JSON 응답을 받지 못했습니다.',{'reason':'INVALID_JSON','model':self.model,'summary':'서버 응답 형식 오류','action':'잠시 후 재검사하세요.'}) from None
    def ask(self,prompt,search=False,json_output=False,timeout_seconds=None):
        payload={'model':self.model,'input':prompt,'store':False}
        if search:
            payload['tools']=[{'type':'google_search'}]
            # Only the officially documented Flash model's retrieval phase uses low thinking.
            # Factual, image and final quality judgments keep their normal settings.
            if self.model=='gemini-3.8-flash':payload['generation_config']={'thinking_level':'low'}
        if json_output: payload['response_format']={'type':'text','mime_type':'application/json','schema':{'type':'object','additionalProperties':True}}
        limit=self.REQUEST_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
        if type(limit) is not int or not 20<=limit<=self.REQUEST_TIMEOUT_SECONDS:raise ValueError('AI 요청 대기 설정 범위 오류')
        previous_timeout=self.request_timeout_seconds;self.request_timeout_seconds=limit
        started=time.monotonic()
        try:raw=self.transport(payload)
        except AIError as exc:
            if exc.diagnostic:
                request_type='검색 근거 조사' if search else '이미지 검사' if isinstance(prompt,list) else '구조화 검사' if json_output else '본문 응답'
                elapsed=round(time.monotonic()-started,1)
                exc.diagnostic.update(request_type=request_type,elapsed_seconds=elapsed,timeout_seconds=limit,input_chars=len(json.dumps(prompt,ensure_ascii=False)),search_enabled=search,thinking_level=payload.get('generation_config',{}).get('thinking_level','default'))
                exc.args=(str(exc)+f'\n요청 종류: {request_type} / 대기 {elapsed}초 / 요청 대기 설정 {limit}초',)
            raise
        finally:self.request_timeout_seconds=previous_timeout

        blocks=output_blocks(raw)
        text='\n'.join(b.get('text','') for b in blocks if b.get('type')=='text')
        citations=[]
        for block in blocks:
            for a in block.get('annotations',[]):
                if a.get('type')=='url_citation' and a.get('url','').startswith('https://'):
                    citations.append({'url':a['url'],'title':a.get('title',''),'start_index':a.get('start_index'),'end_index':a.get('end_index')})
        if not text: raise AIError('AI가 유효한 본문을 반환하지 않았습니다.')
        return {'text':text,'citations':citations,'model':self.model,'search_enabled':search}
    def object(self,prompt):
        response=self.ask(prompt+'\n응답은 JSON 객체 하나만 반환하세요. 코드 블록 및 해설은 제외합니다.',json_output=True)
        return self.parse_object(response['text'])
    @staticmethod
    def parse_object(text):
        text=text.strip()
        if text.startswith('```'): text=re.sub(r'^```(?:json)?\s*|\s*```$','',text)
        try: obj=json.loads(text)
        except ValueError: raise AIError('AI 구조화 응답 오류: 검증 보류') from None
        if not isinstance(obj,dict): raise AIError('AI 응답 객체 형식 오류')
        return obj

    def image_object(self,prompt,image_bytes,mime):
        import base64
        content=[{'type':'text','text':prompt+'\nJSON 객체 하나만 반환하세요.'},
                 {'type':'image','data':base64.b64encode(image_bytes).decode('ascii'),'mime_type':mime}]
        response=self.ask(content,json_output=True)
        return self.parse_object(response['text'])
