"""Fast Gate screens structure; it does not claim to verify facts or image pixels."""
import json
import re
from collections import Counter
from dataclasses import asdict,dataclass
from html.parser import HTMLParser
from urllib.parse import urlparse
from .sync import anomaly,now

ENGINE_VERSION='R3.0-fast-0.2'

class Document(HTMLParser):
    VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
    def __init__(self,html):
        super().__init__(); self.text=[]; self.headings=[]; self.images=[]; self.links=[]; self.stack=[]; self.errors=[]; self.hidden=0
        self.feed(html); self.close()
        if self.stack: self.errors.append('닫히지 않은 태그: '+','.join(self.stack[:5]))
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag in ('script','iframe','object','embed','form','input','button'):
            self.errors.append('공개 본문에 허용되지 않는 태그: '+tag)
        if any(k.lower().startswith('on') for k in attrs): self.errors.append('본문 이벤트 속성 발견')
        if any(str(attrs.get(k,'')).strip().lower().startswith(('javascript:','vbscript:','data:text/html')) for k in ('href','src')):
            self.errors.append('허용되지 않는 링크 방식')
        if tag in ('script','style'): self.hidden+=1
        if tag in ('h1','h2','h3'): self.headings.append(tag)
        if tag=='img': self.images.append(attrs)
        if tag=='a': self.links.append(attrs.get('href',''))
        if tag not in self.VOID: self.stack.append(tag)
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in self.VOID: self.handle_endtag(tag)
    def handle_endtag(self,tag):
        if tag in self.VOID: return
        if tag in ('script','style'): self.hidden=max(0,self.hidden-1)
        if self.stack and self.stack[-1]==tag: self.stack.pop()
        else: self.errors.append('태그 순서 확인: '+tag)
    def handle_data(self,data):
        if not self.hidden: self.text.append(data)

def normalize(text): return re.sub(r'\s+',' ',text).strip().lower()
def shingles(text):
    text=normalize(text)
    return {text[i:i+8] for i in range(max(0,len(text)-7))}

@dataclass
class Result:
    grade:str
    route:str
    issues:list
    metrics:dict
    verified:bool=False

def cached_fast(raw):
    try:result=Result(**json.loads(raw))
    except (ValueError,TypeError):return None
    if (result.grade not in ('EMPTY_TITLE','EMPTY_BODY','EMPTY_BOTH','INCOMPLETE_DRAFT','SCHEDULED_HOLD','NEEDS_DEEP')
        or result.route not in ('ANOMALY','DEEP','EVIDENCE_REUSE_OR_DEEP')
        or not isinstance(result.issues,list) or any(not isinstance(x,str) for x in result.issues)
        or not isinstance(result.metrics,dict) or result.verified is not False):return None
    return result

def fast_check(post,others=()):
    state=post['status']; initial=anomaly(post)
    if initial.startswith('EMPTY_'):
        return Result(initial,'ANOMALY',['제목 또는 본문 누락'],{})
    doc=Document(post['content']); text=' '.join(doc.text); issues=[]
    if len(normalize(text))<1500: issues.append('본문 길이 검토 필요')
    if 'h1' in doc.headings: issues.append('본문 H1 발견')
    if doc.headings.count('h2')<2: issues.append('H2 구성 검토 필요')
    if len(doc.images)<2: issues.append('이미지 2장 미만')
    if any(not x.get('alt','').strip() for x in doc.images): issues.append('ALT 누락')
    if any(not x.get('src','').strip() for x in doc.images): issues.append('이미지 주소 누락')
    own_host=urlparse(post.get('url','')).hostname
    internal=sum(bool(href.startswith('/') and not href.startswith('//')) or bool(own_host and urlparse(href).hostname==own_host) for href in doc.links)
    external=sum(bool(urlparse(href).scheme in ('http','https') and urlparse(href).hostname!=own_host) for href in doc.links)
    if not internal: issues.append('내부링크 확인 필요')
    if not external: issues.append('외부 근거 링크 확인 필요')
    issues.extend(doc.errors[:3])
    if re.search(r'\[[^\]]+\]\(https?://',post['content']): issues.append('미변환 Markdown 링크')
    sentences=[normalize(x) for x in re.split(r'[.!?。\n]',text) if len(normalize(x))>35]
    if any(count>2 for count in Counter(sentences).values()): issues.append('동일 문장 반복')
    tokens=re.findall(r'[가-힣A-Za-z0-9]{2,}',post['title'])
    overlap=sum(token.lower() in text.lower() for token in tokens)/max(1,len(tokens))
    if tokens and overlap<0.25: issues.append('제목·본문 키워드 일치 부족')
    current=shingles(text); similar=[]
    for other in others:
        if str(other['post_id'])==str(post['id']): continue
        prior=shingles(' '.join(Document(other['content']).text))
        score=len(current & prior)/max(1,min(len(current),len(prior)))
        if score>=0.75 and len(current)>=150: similar.append({'post_id':other['post_id'],'overlap':round(score,3)})
    if similar: issues.append('다른 글과 높은 기본 유사도')
    metrics={'text_length':len(normalize(text)),'images':len(doc.images),'internal_links':internal,'external_links':external,'title_overlap':round(overlap,3),'similar_posts':similar}
    grade='SCHEDULED_HOLD' if state=='SCHEDULED' else 'NEEDS_DEEP'
    if initial=='INCOMPLETE_DRAFT': grade=initial
    # Formal checks alone cannot prove factual safety, utility or pixel relevance.
    return Result(grade,'DEEP' if issues else 'EVIDENCE_REUSE_OR_DEEP',issues,metrics)

def run_checks(store,blog_id):
    from .sync import digest
    db=store.db
    rows=[dict(row) for row in db.execute('SELECT * FROM posts WHERE blog_id=? AND present=1',(blog_id,))]
    from .finalize import corpus_hash
    full_corpus_hash=corpus_hash(rows)
    corpus=digest(sorted((r['post_id'],r['content_hash']) for r in rows))
    # This cheap corpus index is separate from per-post structural/AI checks.
    indexed={r['post_id']:shingles(' '.join(Document(r['content']).text)) for r in rows}
    db.execute('CREATE TABLE IF NOT EXISTS duplicate_checks(blog_id TEXT,post_id TEXT,corpus_hash TEXT,details TEXT,PRIMARY KEY(blog_id,post_id))')
    counts={'checked':0,'reused':0,'deep_needed':0}
    with db:
        for row in rows:
            old=db.execute('SELECT grade,details,checked_at FROM recovery_checks WHERE blog_id=? AND post_id=? AND content_hash=? AND engine_version=? ORDER BY id DESC LIMIT 1',(blog_id,row['post_id'],row['content_hash'],ENGINE_VERSION)).fetchone()
            result=cached_fast(old['details']) if old else None
            if result is not None:
                counts['reused']+=1
                db.execute('UPDATE posts SET grade=?,last_checked=? WHERE blog_id=? AND post_id=?',(result.grade,old['checked_at'],blog_id,row['post_id']))
            else:
                result=fast_check(dict(row,id=row['post_id'])); stamp=now()
                db.execute('INSERT INTO recovery_checks(blog_id,post_id,content_hash,engine_version,checked_at,grade,details) VALUES(?,?,?,?,?,?,?)',(blog_id,row['post_id'],row['content_hash'],ENGINE_VERSION,stamp,result.grade,json.dumps(asdict(result),ensure_ascii=False)))
                db.execute('UPDATE posts SET grade=?,last_checked=? WHERE blog_id=? AND post_id=?',(result.grade,stamp,blog_id,row['post_id']))
                counts['checked']+=1
            cached=db.execute('SELECT corpus_hash FROM duplicate_checks WHERE blog_id=? AND post_id=?',(blog_id,row['post_id'])).fetchone()
            if not cached or cached['corpus_hash']!=corpus:
                current=indexed[row['post_id']]; matches=[]
                for pid,prior in indexed.items():
                    if pid==row['post_id']: continue
                    score=len(current & prior)/max(1,min(len(current),len(prior)))
                    if score>=0.75 and len(current)>=150: matches.append({'post_id':pid,'overlap':round(score,3)})
                db.execute('INSERT OR REPLACE INTO duplicate_checks VALUES(?,?,?,?)',(blog_id,row['post_id'],corpus,json.dumps(matches,ensure_ascii=False)))
            counts['deep_needed']+=int(result.route!='ANOMALY')
            full=db.execute('SELECT * FROM recovery_checks WHERE blog_id=? AND post_id=? AND content_hash=? AND engine_version LIKE "R3.0-existing-%" ORDER BY id DESC LIMIT 1',(blog_id,row['post_id'],row['content_hash'])).fetchone()
            if full and result.route!='ANOMALY':
                from .freshness import is_fresh
                try:details=json.loads(full['details'])
                except (ValueError,TypeError):details={}
                if not isinstance(details,dict):details={}
                from .finalize import existing_review_hash
                if full['engine_version']=='R3.0-existing-0.59':
                    context_matches=details.get('review_context_hash')==existing_review_hash(rows,row['post_id'])
                else:
                    context_matches=full['engine_version']=='R3.0-existing-0.23' and details.get('corpus_hash')==full_corpus_hash
                valid=context_matches and is_fresh(full['checked_at'],7200 if row['status']=='SCHEDULED' else 86400)
                allowed={'SCHEDULED_PASS','SCHEDULED_HOLD'} if row['status']=='SCHEDULED' else {'PASS','A','B','C'} if row['status']=='LIVE' else set()
                valid=valid and full['grade'] in allowed
                grade=full['grade'] if valid else 'SCHEDULED_HOLD' if row['status']=='SCHEDULED' else 'NEEDS_DEEP'
                db.execute('UPDATE posts SET grade=? WHERE blog_id=? AND post_id=?',(grade,blog_id,row['post_id']))
    return counts
