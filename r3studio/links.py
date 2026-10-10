"""Use only current LIVE internal targets and evidence-listed external URLs."""
import html
import json
from urllib.parse import urlparse,urljoin,urldefrag
from .gates import Document
from .google import public_fetch

class LinkHold(RuntimeError):pass

def inspect_link_access(content,base_url,fetch=public_fetch,checkpoint=lambda:None):
    from .evidence import display_url
    results=[];seen=set()
    for href in Document(content).links:
        checkpoint()
        if href.startswith('#'):continue
        url=normalized(urljoin(base_url,href))
        if url in seen:continue
        seen.add(url)
        try:parsed=urlparse(url);valid=parsed.scheme in ('https','http') and parsed.hostname and not parsed.username and not parsed.password
        except ValueError:valid=False
        item={'url':display_url(url)}
        if not valid:item['state']='INVALID_URL'
        else:
            try:
                response=fetch(url)
                item.update(state='ACCESSIBLE' if 200<=response['status']<300 else 'HTTP_ERROR',http_status=response['status'],final_url=display_url(response['url']))
            except (OSError,ValueError):item['state']='FETCH_FAILED'
        results.append(item)
    return {'completed':True,'results':results,'factual_support_verified':False}

def normalized(url):return urldefrag(url)[0]

def append_verified_candidates(ai,title,content,live_posts,evidence):
    candidates=[{'id':p['post_id'],'title':p['title'],'url':p['url']} for p in live_posts if p.get('status')=='LIVE' and p.get('url')]
    if not candidates:raise LinkHold('연결 가능한 LIVE 글이 없습니다.')
    choice=ai.object('제목과 본문을 읽고 독자에게 실제로 도움이 되는 관련 LIVE 글을 1~3개 선택하세요. ids:[정확한 Post ID]. 관련 글이 없으면 빈 배열. 후보에 없는 ID를 생성하지 마세요.\n'+json.dumps({'title':title,'article':content,'candidates':candidates},ensure_ascii=False))
    ids=choice.get('ids');lookup={p['id']:p for p in candidates}
    if not isinstance(ids,list) or not 1<=len(ids)<=3 or len(set(ids))!=len(ids) or any(i not in lookup for i in ids):raise LinkHold('관련 LIVE 링크 선택 미통과')
    links=''.join('<li><a href="'+html.escape(lookup[i]['url'],quote=True)+'">'+html.escape(lookup[i]['title'])+'</a></li>' for i in ids)
    sources=evidence.get('sources',[])
    refs=''.join('<li><a href="'+html.escape(s['url'],quote=True)+'">'+html.escape(s.get('title') or s.get('reason') or '근거 자료 '+str(index+1))+'</a></li>' for index,s in enumerate(sources) if s.get('grade') in ('A','B'))
    return content+'<h2>함께 읽으면 도움이 되는 글</h2><ul>'+links+'</ul><h2>참고 자료</h2><ul>'+refs+'</ul>'

def check_links(content,base_url,live_posts,evidence,fetch=public_fetch):
    own_host=urlparse(base_url).hostname
    live={normalized(p['url']) for p in live_posts if p.get('status')=='LIVE' and p.get('url')}
    sources={normalized(s['url']) for s in evidence.get('sources',[]) if s.get('grade') in ('A','B')}
    results=[];seen=set();internal=external=0
    for href in Document(content).links:
        if href.startswith('#'):continue
        url=normalized(urljoin(base_url,href))
        if url in seen:continue
        seen.add(url);parsed=urlparse(url)
        if parsed.scheme not in ('http','https') or not parsed.hostname:raise LinkHold('검증 불가 링크 방식')
        kind='internal' if parsed.hostname==own_host else 'external'
        if kind=='internal' and url not in live:raise LinkHold('공개 LIVE 목록에 없는 내부링크')
        if kind=='external' and url not in sources:raise LinkHold('근거 장부 밖의 외부링크')
        response=fetch(url)
        if not 200<=response['status']<300:raise LinkHold('링크 HTTP 오류')
        final=normalized(response['url'])
        if kind=='internal' and final not in live:raise LinkHold('내부링크 리다이렉트 목적지가 LIVE 글이 아님')
        if kind=='external' and urlparse(final).hostname!=parsed.hostname:raise LinkHold('외부 근거 도메인 변경: 확인 필요')
        results.append({'url':url,'kind':kind,'status':response['status'],'final_url':final})
        internal+=kind=='internal';external+=kind=='external'
    if not internal or not external:raise LinkHold('내부링크와 외부 근거 링크가 모두 필요합니다.')
    return {'pass':True,'internal':internal,'external':external,'results':results}
