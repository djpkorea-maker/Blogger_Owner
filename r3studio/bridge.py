"""Blogger Bridge R3 read-only client. Never sends write actions."""
import json
import os
import urllib.request
from urllib.parse import urlparse

class BridgeError(RuntimeError): pass

class BridgeAdapter:
    def __init__(self,url,secret,blog_id,transport=None):
        from .readiness import bridge_url_valid
        if not bridge_url_valid(url):
            raise ValueError('Apps Script /exec HTTPS 주소를 입력하세요.')
        if not secret: raise ValueError('Bridge 인증값이 필요합니다.')
        self.url,self.secret,self.blog_id=url,secret,str(blog_id)
        self.transport=transport or self._http
        self.progress=lambda *args:None
        self.checkpoint=lambda:None
    def set_observer(self,progress,checkpoint):
        self.progress,self.checkpoint=progress,checkpoint
    @classmethod
    def from_environment(cls):
        return cls(os.environ.get('R3_BRIDGE_URL',''),os.environ.get('R3_BRIDGE_SECRET',''),os.environ.get('R3_BLOG_ID',''))
    def _http(self,body):
        req=urllib.request.Request(self.url,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'},method='POST')
        try:
            with urllib.request.urlopen(req,timeout=45) as response:
                data=response.read(12*1024*1024+1)
                if len(data)>12*1024*1024: raise BridgeError('Bridge 응답 크기 초과')
                return json.loads(data)
        except (OSError,ValueError):
            raise BridgeError('Bridge 조회 실패: 연결 주소와 배포 권한을 확인하세요.') from None
    def _call(self,action,payload):
        result=self.transport({'secret':self.secret,'action':action,'payload':payload})
        if not isinstance(result,dict) or result.get('ok') is not True:
            raise BridgeError('Bridge 조회 거절: 설정 또는 API 권한을 확인하세요.')
        if str(result.get('blogId'))!=self.blog_id: raise BridgeError('다른 블로그 응답: 동기화 중지')
        return result
    def list_metadata(self):
        all_posts=[]; seen_ids=set()
        for state in ('LIVE','SCHEDULED','DRAFT'):
            token=''; seen_tokens=set()
            while True:
                self.checkpoint()
                result=self._call('list_metadata',{'status':state,'pageToken':token})
                self.checkpoint()
                if result.get('status')!=state or not isinstance(result.get('items'),list):
                    raise BridgeError('불완전한 상태별 목록')
                for post in result['items']:
                    pid=str(post.get('id',''))
                    if not pid or pid in seen_ids or post.get('status')!=state or not post.get('updated'):
                        raise BridgeError('목록 충돌 또는 필수 정보 누락')
                    seen_ids.add(pid); all_posts.append(post)
                self.progress('Blogger '+state+' 목록',len(all_posts),0)
                token=result.get('nextPageToken','')
                if not isinstance(token,str): raise BridgeError('잘못된 페이지 토큰')
                if not token: break
                if token in seen_tokens: raise BridgeError('반복 페이지 감지')
                seen_tokens.add(token)
        return all_posts
    def get_post(self,pid):
        post=self._call('get_post',{'postId':str(pid)}).get('post')
        if not isinstance(post,dict) or str(post.get('id'))!=str(pid) or 'content' not in post:
            raise BridgeError('잘못된 단건 응답')
        return post

# Write-capable client is opt-in; the read client remains unchanged.
from .apply import WriteBridgeMixin
class WriteBridgeAdapter(WriteBridgeMixin,BridgeAdapter):
    pass
