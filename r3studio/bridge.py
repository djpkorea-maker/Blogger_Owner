"""Blogger Bridge R3 read-only client. Never sends write actions."""
import json
import os
import urllib.request
import urllib.error
import socket
import time
from urllib.parse import urlparse

class BridgeError(RuntimeError):
    def __init__(self,message,diagnostic=None):
        super().__init__(message);self.diagnostic=diagnostic

def bridge_failure(reason,http_status=None,elapsed=None):
    summaries={'TIMEOUT':'Blogger Bridge 응답 시간 초과','NETWORK':'Blogger Bridge 네트워크 연결 실패','HTTP_ERROR':'Blogger Bridge HTTP 요청 실패','INVALID_JSON':'Blogger Bridge가 JSON 대신 다른 응답을 반환했습니다.','REJECTED':'Blogger Bridge가 요청을 거절했습니다.'}
    d={'reason':reason,'summary':summaries[reason],'stage':'Blogger 조회','action':'작업 기록의 오류 분류를 확인하세요. 인증값을 다시 입력하기 전에 원인을 확인해야 합니다.'}
    if http_status is not None:d['http_status']=http_status
    if elapsed is not None:d['elapsed_seconds']=round(elapsed,1)
    return BridgeError(d['summary'],d)

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
        started=time.monotonic()
        req=urllib.request.Request(self.url,data=json.dumps(body).encode(),headers={'Content-Type':'application/json'},method='POST')
        try:
            with urllib.request.urlopen(req,timeout=45) as response:
                data=response.read(12*1024*1024+1)
                if len(data)>12*1024*1024: raise BridgeError('Bridge 응답 크기 초과')
                return json.loads(data)
        except urllib.error.HTTPError as exc:
            raise bridge_failure('HTTP_ERROR',exc.code,time.monotonic()-started) from None
        except urllib.error.URLError as exc:
            reason='TIMEOUT' if isinstance(exc.reason,(TimeoutError,socket.timeout)) else 'NETWORK'
            raise bridge_failure(reason,elapsed=time.monotonic()-started) from None
        except (TimeoutError,socket.timeout):
            raise bridge_failure('TIMEOUT',elapsed=time.monotonic()-started) from None
        except OSError:
            raise bridge_failure('NETWORK',elapsed=time.monotonic()-started) from None
        except ValueError:
            raise bridge_failure('INVALID_JSON',elapsed=time.monotonic()-started) from None
    def _call(self,action,payload):
        result=self.transport({'secret':self.secret,'action':action,'payload':payload})
        if not isinstance(result,dict) or result.get('ok') is not True:
            # Never store raw server errors: they may contain deployment addresses or tokens.
            import re
            match=re.fullmatch(r'blogger_http_(\d{3})',str(result.get('error',''))) if isinstance(result,dict) else None
            raise bridge_failure('REJECTED',int(match[1]) if match else None)
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
