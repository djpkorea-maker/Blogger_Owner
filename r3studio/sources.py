"""Fetch original HTML/plain text and verify exact supporting spans."""
import json
from io import BytesIO
from pypdf import PdfReader
from pypdf.errors import PyPdfError
import re
from datetime import datetime,timezone
from html.parser import HTMLParser
from urllib.parse import urlparse
from .google import public_fetch
from .sync import digest,now
from .evidence import EvidenceHold

class Extract(HTMLParser):
    def __init__(self,html):
        super().__init__();self.skip=0;self.text=[];self.feed(html)
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','nav','footer'):self.skip+=1
        if not self.skip and tag in ('p','div','h1','h2','h3','li','br','tr','td','section','article'):self.text.append(' ')
    def handle_endtag(self,tag):
        if tag in ('script','style','nav','footer'):self.skip=max(0,self.skip-1)
        if not self.skip and tag in ('p','div','h1','h2','h3','li','tr','td','section','article'):self.text.append(' ')
    def handle_data(self,data):
        if not self.skip:self.text.append(data)
def norm(text):return re.sub(r'\s+',' ',text).strip()

def original_fetch(url):return public_fetch(url,raw=True)

def pdf_text(data):
    if not isinstance(data,bytes) or not data.startswith(b'%PDF-'):raise EvidenceHold('PDF 원문 바이트 확인 불가')
    reader=PdfReader(BytesIO(data))
    if reader.is_encrypted:raise EvidenceHold('암호화된 PDF 원문')
    if len(reader.pages)>80:raise EvidenceHold('PDF 80쪽 제한 초과')
    parts=[]
    for page in reader.pages:
        stream=page.get_contents()
        if stream and len(stream.get_data())>20*1024*1024:raise EvidenceHold('PDF 페이지 추출 크기 제한 초과')
        parts.append(page.extract_text() or '')
    return norm(' '.join(parts))

class SourceReader:
    def __init__(self,store,fetch=original_fetch):
        self.store,self.fetch=store,fetch
        store.db.execute('CREATE TABLE IF NOT EXISTS source_originals(url TEXT PRIMARY KEY,checked_at TEXT,status TEXT,payload TEXT)');store.db.commit()
    def cached(self,url):
        old=self.store.db.execute('SELECT * FROM source_originals WHERE url=?',(url,)).fetchone()
        if old:
            try:
                age=(datetime.now(timezone.utc)-datetime.fromisoformat(old['checked_at'])).total_seconds()
                cached=json.loads(old['payload'])
                if isinstance(cached,dict) and 0<=age<86400 and old['status']=='FETCHED' and cached.get('extract_version')==64 and isinstance(cached.get('text'),str) and cached.get('text_hash')==digest(cached['text']):return cached
            except (ValueError,TypeError):pass
        return None
    def read_many(self,sources,progress):
        # Only network I/O runs in workers; SQLite and document parsing stay here.
        from concurrent.futures import ThreadPoolExecutor,as_completed
        results={};pending=[]
        for source in sources:
            cached=self.cached(source['url'])
            if cached:results[source['id']]=cached
            else:pending.append(source)
        progress('근거 원문 확인',len(results),len(sources))
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures={pool.submit(self.fetch,s['url']):s for s in pending}
            for future in as_completed(futures):
                source=futures[future]
                try:response=future.result();error=None
                except (OSError,ValueError) as exc:response=None;error=exc
                results[source['id']]=self.read(source['url'],response,error)
                progress('근거 원문 확인',len(results),len(sources))
        return results
    def read(self,url,response=None,error=None):
        cached=self.cached(url)
        if cached:return cached
        result={'url':url,'status':'UNAVAILABLE','checked_at':now()}
        try:
            if error is not None:raise error
            response=response if response is not None else self.fetch(url);ctype={k.lower():v for k,v in response['headers'].items()}.get('content-type','').lower()
            if not 200<=response['status']<300:raise EvidenceHold('원문 HTTP 오류')
            if 'image/' in ctype:raise EvidenceHold('이미지 원문: 텍스트 추출 불가')
            text=pdf_text(response.get('body_bytes')) if 'pdf' in ctype or response.get('body_bytes',b'').startswith(b'%PDF-') else (norm(''.join(Extract(response['body']).text)) if 'html' in ctype or re.search(r'<(?:html|p|div|article|h[1-6])\b',response['body'][:1000],re.I) else norm(response['body']))
            if len(text)<100:raise EvidenceHold('원문 본문 부족 또는 로그인 화면')
            result.update(status='FETCHED',extract_version=64,final_url=response['url'],text=text[:50000],text_hash=digest(text[:50000]),full_text_hash=digest(text),truncated=len(text)>50000)
        except EvidenceHold as exc:result['reason']=str(exc)
        except TimeoutError:result['reason']='원문 요청 시간 초과 (20초)'
        except (OSError,ValueError,PyPdfError):result['reason']='원문 네트워크 오류 또는 문서 파싱 실패'
        with self.store.db:self.store.db.execute('INSERT OR REPLACE INTO source_originals VALUES(?,?,?,?)',(url,now(),result['status'],json.dumps(result,ensure_ascii=False)))
        return result

def verify_origins(ai,pack,reader,progress=lambda *args:None):
    from .evidence import display_url
    originals={};supported=set();rejections={};verified=[];trusted=set();format_diagnostic={};format_trace=[]
    def fail(message):
        diagnostic={'reason':'EVIDENCE_ORIGINALS_INCOMPLETE','summary':message,'stage':'근거 원문 확인','action':'아래 미검증 주장과 원문 접근 상태를 확인하세요. 미검증은 사실 오류 판정이 아닙니다.',
            'unverified_claims':[{'text':f['text'],'reason':rejections.get(f['id'],message)} for f in pack['facts'] if f['id'] not in supported],
            'search_urls':[display_url(source['url']) for source in pack['sources']],
            'source_checks':[{'url':display_url(source['url']),'state':originals.get(source['id'],{}).get('status','NOT_CHECKED'),'reason':originals.get(source['id'],{}).get('reason','')} for source in pack['sources']]}
        diagnostic.update(format_diagnostic)
        if format_trace:diagnostic['response_format_attempts']=format_trace
        error=EvidenceHold(message,diagnostic=diagnostic)
        # Incomplete evidence is useful for diagnosis, never for a PASS verdict.
        from copy import deepcopy
        partial=deepcopy(pack)
        partial.pop('original_verification',None)
        partial['evidence_review']={'diagnostic_only':True,'diagnostic':diagnostic,
            'supported_fact_ids':sorted(supported),'claims':verified,
            'trusted_sources':sorted(trusted),'originals':originals}
        error.partial_pack=partial
        raise error
    if hasattr(reader,'read_many'):originals=reader.read_many(pack['sources'],progress)
    else:
        for index,source in enumerate(pack['sources']):
            progress('근거 원문 확인',index+1,len(pack['sources']))
            originals[source['id']]=reader.read(source['url'])
    usable={sid:value for sid,value in originals.items() if value['status']=='FETCHED'}
    if len(usable)<2:fail('직접 확인 가능한 원문 2개 미만')
    from .origin_response import request_review
    try:review,format_trace=request_review(ai,{'facts':pack['facts'],'sources':pack['sources'],'originals':usable},progress)
    except EvidenceHold as exc:
        format_diagnostic=exc.diagnostic
        fail(str(exc))
    source_reviews=review.get('sources');claims=review.get('claims')
    if not isinstance(source_reviews,list) or not isinstance(claims,list):fail('원문 검사 응답 형식 오류')
    trusted=set();publishers=set();roots=set()
    for item in source_reviews:
        if not isinstance(item,dict):continue
        sid=item.get('source_id');publisher=item.get('publisher')
        if sid in usable and item.get('grade') in ('A','B') and isinstance(publisher,str) and publisher.strip():
            host=urlparse(usable[sid]['final_url']).hostname
            if not host:continue
            trusted.add(sid);publishers.add(norm(publisher).lower());roots.add('.'.join(host.split('.')[-2:]))
    if len(trusted)<2 or len(publishers)<2 or len(roots)<2:fail('확인된 독립 출처 2개 미만')
    fact_ids={f['id'] for f in pack['facts']};supported=set();verified=[]
    for claim in claims:
        if not isinstance(claim,dict):continue
        sid=claim.get('source_id');quote=claim.get('quote');fid=claim.get('fact_id')
        if fid not in fact_ids:continue
        if sid not in trusted or claim.get('supported') is not True or not isinstance(quote,str):
            rejections[fid]='연결된 원문 미확보 또는 원문 검사에서 직접 지원하지 않음';continue
        if not 10<=len(norm(quote))<=250 or norm(quote) not in usable[sid]['text']:
            rejections[fid]='제시된 인용 구절이 실제 추출 원문과 일치하지 않음';continue
        fact=next(f for f in pack['facts'] if f['id']==fid)
        if sid not in fact['source_ids']:continue
        supported.add(fid);verified.append(claim)
    if any(f.get('core') is True and f['id'] not in supported for f in pack['facts']):fail('원문으로 지원되지 않는 핵심 사실')
    if len(supported)<4:fail('원문에서 확인된 사실 4개 미만')
    pack['original_verification']={'checked_at':now(),'pack_hash':digest({'sources':pack['sources'],'facts':pack['facts']}),'originals':originals,'claims':verified,'trusted_sources':sorted(trusted),'response_format_attempts':format_trace}
    return pack

def require_originals(pack):
    verification=pack.get('original_verification',{})
    if not isinstance(verification,dict):raise EvidenceHold('원문 확인 기록 형식 오류')
    if verification.get('pack_hash')!=digest({'sources':pack.get('sources'),'facts':pack.get('facts')}):raise EvidenceHold('근거 원문 확인 누락 또는 근거 변경')
    from .freshness import is_fresh
    if not is_fresh(verification.get('checked_at'),7*86400):raise EvidenceHold('원문 확인 결과 만료 또는 확인시각 오류')
    originals=verification.get('originals');claims=verification.get('claims');trusted=verification.get('trusted_sources')
    if not isinstance(originals,dict) or not isinstance(claims,list) or not isinstance(trusted,list):raise EvidenceHold('원문·인용 검사 기록 누락')
    source_ids={s['id'] for s in pack['sources']};trusted=set(s for s in trusted if isinstance(s,str) and s in source_ids)
    roots=set()
    for sid in trusted:
        original=originals.get(sid,{})
        if not isinstance(original,dict) or original.get('status')!='FETCHED' or not isinstance(original.get('text'),str) or original.get('text_hash')!=digest(original['text']):raise EvidenceHold('저장된 원문 변경 또는 손상')
        try:host=urlparse(original.get('final_url','')).hostname
        except ValueError:host=None
        if not host:raise EvidenceHold('원문 주소 기록 오류')
        roots.add('.'.join(host.split('.')[-2:]))
    if len(trusted)<2 or len(roots)<2:raise EvidenceHold('독립 원문 검사 기록 부족')
    facts={f['id']:f for f in pack['facts']};supported=set()
    for claim in claims:
        if not isinstance(claim,dict):raise EvidenceHold('인용 검사 기록 형식 오류')
        fid=claim.get('fact_id');sid=claim.get('source_id');quote=claim.get('quote')
        if not isinstance(fid,str) or not isinstance(sid,str) or fid not in facts or sid not in trusted or sid not in facts[fid]['source_ids'] or claim.get('supported') is not True or not isinstance(quote,str):raise EvidenceHold('주장과 원문 연결 기록 오류')
        if not 10<=len(norm(quote))<=250 or norm(quote) not in originals[sid]['text']:raise EvidenceHold('저장된 근거 구절 확인 불가')
        supported.add(fid)
    if len(supported)<4 or any(f.get('core') is True and fid not in supported for fid,f in facts.items()):raise EvidenceHold('핵심 사실 원문 검사 기록 부족')
