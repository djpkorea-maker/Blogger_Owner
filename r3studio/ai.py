"""Gemini Interactions REST client; explicit model, no credentials in artifacts."""
import json
import os
import re
import urllib.request

class AIError(RuntimeError): pass

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
    def __init__(self,key,model,transport=None):
        if not key or not re.fullmatch(r'[A-Za-z0-9._-]+',model):
            raise AIError('Gemini API 키와 모델명을 설정하세요.')
        self.key,self.model,self.transport=key,model,transport or self._http
    @classmethod
    def from_environment(cls):
        return cls(os.environ.get('R3_GEMINI_KEY',''),os.environ.get('R3_GEMINI_MODEL',''))
    def _http(self,payload):
        req=urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/interactions',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','x-goog-api-key':self.key},method='POST')
        try:
            with urllib.request.urlopen(req,timeout=55) as res:
                data=res.read(8*1024*1024+1)
                if len(data)>8*1024*1024: raise AIError('AI 응답 크기 초과')
                return json.loads(data)
        except (OSError,ValueError): raise AIError('AI 연결 실패: API 설정, 모델 권한, 사용량을 확인하세요.') from None
    def ask(self,prompt,search=False,json_output=False):
        payload={'model':self.model,'input':prompt,'store':False}
        if search: payload['tools']=[{'type':'google_search'}]
        if json_output: payload['response_format']={'type':'text','mime_type':'application/json','schema':{'type':'object','additionalProperties':True}}
        raw=self.transport(payload)
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
