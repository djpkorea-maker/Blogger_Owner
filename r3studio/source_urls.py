"""Resolve only selected Google grounding links; never infer publishers from a relay."""
import urllib.request
import urllib.error
from urllib.parse import urlparse
from .evidence import EvidenceHold,display_url

RELAY='vertexaisearch.cloud.google.com'
def is_relay(url):
    return urlparse(url).hostname==RELAY and urlparse(url).path.startswith('/grounding-api-redirect/')

def resolve(url):
    if not is_relay(url):return url
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,headers,newurl):
            p=urlparse(newurl)
            if p.scheme!='https' or not p.hostname or p.username or p.password:raise ValueError('Unsupported source destination')
            return super().redirect_request(req,fp,code,msg,headers,newurl)
    opener=urllib.request.build_opener(Redirect())
    for method in ('HEAD','GET'):
        request=urllib.request.Request(url,method=method,headers={'User-Agent':'R3-Evidence/0.63','Range':'bytes=0-0'})
        try:
            with opener.open(request,timeout=15) as response:
                final=response.url;p=urlparse(final)
                if not 200<=response.status<300 or is_relay(final) or p.scheme!='https' or not p.hostname or p.username or p.password:raise ValueError('Unresolved source')
                return final
        except urllib.error.HTTPError as exc:
            if method=='HEAD' and exc.code in (405,501):continue
            break
        except (OSError,ValueError):break
    raise EvidenceHold('선택한 검색 출처의 실제 목적지 확인 실패',diagnostic={'reason':'SOURCE_REDIRECT_UNRESOLVED','summary':'선택한 검색 출처의 실제 목적지 확인 실패','stage':'실제 출처 주소 확인','action':'출처 확인 실패를 자료 부족과 구분하세요. 임의의 주소로 대체하지 않습니다.','search_urls':[display_url(url)]})

def resolve_pack(pack,resolver=resolve,progress=lambda *args:None):
    mappings=[]
    if len(pack['sources'])>8:raise EvidenceHold('근거 장부의 출처가 8개를 초과했습니다. 핵심 주장별 대표 원문으로 정리해야 합니다.')
    for index,source in enumerate(pack['sources'],1):
        progress('실제 출처 주소 확인',index,len(pack['sources']))
        original=source['url'];final=resolver(original)
        if not isinstance(final,str) or is_relay(final):raise EvidenceHold('검색 출처 중계 주소 해석 미완료')
        mappings.append({'search_url':original,'final_url':final})
        source['url']=final
    pack['source_url_mappings']=mappings
    return pack
