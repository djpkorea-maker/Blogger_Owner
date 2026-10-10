"""Separate current public HTTP observations from Google's indexed snapshot."""
import json
import os
import re
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin,urlparse
from .sync import now
from .freshness import is_fresh

def cached_observation(value):
    try:result=json.loads(value)
    except (ValueError,TypeError):return {}
    if not isinstance(result,dict):return {}
    if not isinstance(result.get('public_crawl'),dict):return {}
    for key in ('technical_status','index_status'):
        if not isinstance(result.get(key),str):return {}
    for key in ('problems','changes','new_problems','resolved_problems'):
        if key in result and (not isinstance(result[key],list) or any(not isinstance(x,str) for x in result[key])):return {}
    return result

class Page(HTMLParser):
    def __init__(self,text):
        super().__init__();self.canonical=[];self.robots=[];self.feed(text)
    def handle_starttag(self,tag,attrs):
        a={k:(v or '') for k,v in attrs}
        if tag=='link' and 'canonical' in a.get('rel','').lower().split():self.canonical.append(a.get('href',''))
        if tag=='meta' and a.get('name','').lower() in ('robots','googlebot'):self.robots.append(a.get('content',''))

def blocks_index(value,header=False):
    applicable=True
    for part in value.lower().split(','):
        part=part.strip()
        scoped=re.fullmatch(r'([a-z][a-z0-9_-]*):\s*(.*)',part)
        if scoped:
            name,part=scoped.groups()
            if name in ('max-image-preview','max-snippet','max-video-preview','unavailable_after'):continue
            if not header:continue
            applicable=name in ('googlebot','*')
        if applicable and set(part.split()) & {'noindex','none'}:return True
    return False

def public_fetch(url,raw=False):
    p=urlparse(url)
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:raise ValueError('잘못된 공개 URL')
    chain=[]
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,headers,newurl):
            if len(chain)>=10:raise ValueError('리다이렉트 10회 초과')
            chain.append({'status':code,'from':req.full_url,'to':newurl})
            return super().redirect_request(req,fp,code,msg,headers,newurl)
    req=urllib.request.Request(url,headers={'User-Agent':'R3-Blogger-Status/0.4'})
    try:
        with urllib.request.build_opener(Redirect()).open(req,timeout=20) as res:
            limit=(8 if raw else 2)*1024*1024
            body=res.read(limit+1)
            if len(body)>limit:raise ValueError('응답 본문 크기 초과')
            charset=res.headers.get_content_charset() or 'utf-8'
            try:text=body.decode(charset,errors='replace')
            except LookupError:text=body.decode('utf-8',errors='replace')
            return {'status':res.status,'url':res.url,'headers':dict(res.headers),'body':text,**({'body_bytes':body} if raw else {}),'redirects':chain}
    except urllib.error.HTTPError as exc:
        return {'status':exc.code,'url':exc.url,'headers':dict(exc.headers),'body':'','redirects':chain}

class SearchConsole:
    def __init__(self,token,property_url,transport=None):
        self.token,self.property_url,self.transport=token,property_url,transport or self._http
    def _http(self,payload):
        req=urllib.request.Request('https://searchconsole.googleapis.com/v1/urlInspection/index:inspect',data=json.dumps(payload).encode(),headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'},method='POST')
        try:
            with urllib.request.urlopen(req,timeout=25) as res:
                data=res.read(2*1024*1024+1)
                if len(data)>2*1024*1024:raise ValueError('Search Console 응답 크기 초과')
                return json.loads(data)
        except (OSError,ValueError):raise ValueError('Search Console 조회 실패: 권한 또는 토큰 유효기간 확인') from None
    def inspect(self,url):
        raw=self.transport({'inspectionUrl':url,'siteUrl':self.property_url,'languageCode':'en-US'})
        if not isinstance(raw,dict) or not isinstance(raw.get('inspectionResult'),dict):raise ValueError('Search Console 응답 형식 오류')
        result=raw['inspectionResult'].get('indexStatusResult')
        if not isinstance(result,dict):raise ValueError('Search Console 색인 응답 누락')
        for key in ('verdict','coverageState','pageFetchState','robotsTxtState'):
            if key in result and not isinstance(result[key],str):raise ValueError('Search Console 상태 형식 오류')
        return result

def index_grade(result):
    if not isinstance(result,dict) or not result:return '확인 불가'
    coverage=result.get('coverageState') or '';fetch=result.get('pageFetchState','')
    if not isinstance(coverage,str):return '확인 불가'
    coverage=coverage.lower()
    if fetch=='SOFT_404' or 'soft 404' in coverage:return 'soft 404'
    if fetch=='NOT_FOUND':return '404'
    if fetch=='SERVER_ERROR':return '서버 오류'
    if 'discovered' in coverage and 'not indexed' in coverage:return '발견됨-미색인'
    if 'crawled' in coverage and 'not indexed' in coverage:return '크롤링됨-미색인'
    if result.get('verdict')=='PASS':return '색인됨'
    # Keep all other canonical/noindex/block reasons without inventing a category.
    return '미색인·세부 확인' if result.get('verdict') in ('FAIL','NEUTRAL') else '확인 불가'

class Monitor:
    def __init__(self,store,fetch=public_fetch,console=None):
        self.store,self.fetch,self.console=store,fetch,console
        from .crawl import CrawlInspector
        self.crawl=CrawlInspector(store,fetch)
    def check(self,blog_id,pid,url,max_age_hours=24,post_fingerprint=None):
        db=self.store.db
        old=db.execute('SELECT * FROM google_status WHERE blog_id=? AND post_id=? AND url=? ORDER BY id DESC LIMIT 1',(blog_id,pid,url)).fetchone()
        previous=cached_observation(old['evidence']) if old else {}
        if old:
            evidence=previous
            expected_mode='search_console' if self.console else 'public_only'
            ttl=24 if old['technical_status']=='ACCESSIBLE' and old['index_status']=='색인됨' and not evidence.get('needs_attention',True) else 2
            if evidence and is_fresh(old['checked_at'],min(max_age_hours,ttl)*3600) and evidence.get('post_fingerprint')==post_fingerprint and evidence.get('mode')==expected_mode and evidence.get('monitor_version')==41:return evidence,True
        observation={'checked_at':now(),'monitor_version':41,'post_fingerprint':post_fingerprint,'mode':'search_console' if self.console else 'public_only','robots_txt':'확인 불가','sitemap':'확인 불가'}
        try:
            response=self.fetch(url);headers={k.lower():v for k,v in response['headers'].items()}
            page=Page(response['body']);status=response['status'];final=response['url']
            noindex=any(blocks_index(x) for x in page.robots) or blocks_index(headers.get('x-robots-tag',''),header=True)
            canonical=[urljoin(final,x) for x in page.canonical]
            tech='404' if status==404 else 'SERVER_ERROR' if status>=500 else 'HTTP_ERROR' if status>=400 else 'NOINDEX' if noindex else 'REDIRECT' if response['redirects'] else 'ACCESSIBLE'
            canonical_review=len(canonical)>1 or bool(canonical and canonical[0]!=final) or any(not x for x in page.canonical)
            if canonical_review and tech=='ACCESSIBLE':tech='CANONICAL_REVIEW'
            observation.update(http_status=status,final_url=final,redirects=response['redirects'],canonical=canonical,canonical_review=canonical_review,robots_meta=page.robots,noindex=noindex)
        except (OSError,ValueError):tech='FETCH_FAILED';observation['fetch_error']='공개 접근 확인 실패'
        observation['public_crawl']=self.crawl.inspect(url)
        result={}
        if self.console:
            try:result=self.console.inspect(url)
            except ValueError:observation['console_error']='Search Console 확인 불가'
        grade=index_grade(result);observation['index_evidence']=result
        if result:observation['robots_txt']=result.get('robotsTxtState','확인 불가');observation['sitemap']=result.get('sitemap',[])
        observation.update(technical_status=tech,index_status=grade)
        # Ignore check time while detecting meaningful change.
        fields=('technical_status','index_status','http_status','final_url','canonical','noindex','robots_txt','sitemap','public_crawl','index_evidence')
        observation['changes']=[k for k in fields if previous and previous.get(k)!=observation.get(k)]
        observation['changed']=bool(observation['changes'])
        observation['needs_attention']=tech!='ACCESSIBLE' or grade not in ('색인됨','확인 불가') or observation['public_crawl']['robots_state']=='BLOCKED' or bool(observation.get('console_error'))
        problems=[]
        if tech!='ACCESSIBLE':problems.append('public:'+tech)
        if grade not in ('색인됨','확인 불가'):problems.append('index:'+grade)
        if observation['public_crawl']['robots_state']=='BLOCKED':problems.append('robots:BLOCKED')
        if observation.get('console_error'):problems.append('console:UNAVAILABLE')
        previous_problems=previous.get('problems',[])
        observation['first_check']=not bool(old)
        observation['previous_record_unusable']=bool(old) and not bool(previous)
        observation['problems']=problems
        observation['new_problems']=[p for p in problems if p not in previous_problems]
        observation['resolved_problems']=[p for p in previous_problems if p not in problems]
        observation['new_problem']=bool(observation['new_problems'])
        observation['persistent_problem']=bool(set(problems)&set(previous_problems))
        with db:db.execute('INSERT INTO google_status(blog_id,post_id,checked_at,url,technical_status,index_status,evidence) VALUES(?,?,?,?,?,?,?)',(blog_id,pid,now(),url,tech,grade,json.dumps(observation,ensure_ascii=False)))
        return observation,False
