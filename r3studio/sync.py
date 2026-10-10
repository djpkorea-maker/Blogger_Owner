"""Read-only sync core. Adapter must yield complete ADMIN metadata for all states."""
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from html.parser import HTMLParser

SCHEMA = '''
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS posts(blog_id TEXT,post_id TEXT,status TEXT,updated TEXT,title TEXT,url TEXT,content TEXT,content_hash TEXT,image_hash TEXT,grade TEXT,last_checked TEXT,present INTEGER NOT NULL DEFAULT 1,PRIMARY KEY(blog_id,post_id));
CREATE TABLE IF NOT EXISTS post_versions(id INTEGER PRIMARY KEY,blog_id TEXT,post_id TEXT,captured_at TEXT,payload TEXT,content_hash TEXT);
CREATE TABLE IF NOT EXISTS recovery_checks(id INTEGER PRIMARY KEY,blog_id TEXT,post_id TEXT,content_hash TEXT,engine_version TEXT,checked_at TEXT,grade TEXT,details TEXT);
CREATE TABLE IF NOT EXISTS generation_history(id INTEGER PRIMARY KEY,created_at TEXT,topic TEXT,title TEXT,status TEXT,details TEXT);
CREATE TABLE IF NOT EXISTS image_checks(id INTEGER PRIMARY KEY,blog_id TEXT,post_id TEXT,image_hash TEXT,checked_at TEXT,result TEXT,details TEXT);
CREATE TABLE IF NOT EXISTS google_status(id INTEGER PRIMARY KEY,blog_id TEXT,post_id TEXT,checked_at TEXT,url TEXT,technical_status TEXT,index_status TEXT,evidence TEXT);
CREATE TABLE IF NOT EXISTS apply_history(id INTEGER PRIMARY KEY,blog_id TEXT,post_id TEXT,created_at TEXT,expected_hash TEXT,actual_hash TEXT,status TEXT,backup_ref TEXT,details TEXT);
CREATE TABLE IF NOT EXISTS sync_runs(id INTEGER PRIMARY KEY,blog_id TEXT,started_at TEXT,finished_at TEXT,status TEXT,details TEXT);
'''

def now():
    return datetime.now(timezone.utc).isoformat()

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def post_hash(post):
    return digest({k:post.get(k,default) for k,default in [('title',''),('content',''),('labels',[]),('status','')]})

class Body(HTMLParser):
    def __init__(self,content):
        super().__init__(); self.text=[]; self.images=[]; self.hidden=0
        self.feed(content)
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'): self.hidden+=1
        if tag=='img': self.images.append(dict(attrs).get('src',''))
    def handle_endtag(self,tag):
        if tag in ('script','style'): self.hidden=max(0,self.hidden-1)
    def handle_data(self,data):
        if not self.hidden: self.text.append(data)

def anomaly(post):
    body=Body(post.get('content','')); title=bool(post.get('title','').strip())
    meaningful=bool(''.join(body.text).replace('\xa0',' ').strip() or body.images)
    if not title and not meaningful: return 'EMPTY_BOTH'
    if not title: return 'EMPTY_TITLE'
    if not meaningful: return 'EMPTY_BODY'
    # A short draft is a review candidate, not a confirmed quality failure.
    if post['status']=='DRAFT' and len(''.join(body.text).strip())<1500: return 'INCOMPLETE_DRAFT'
    if post['status']=='SCHEDULED': return 'SCHEDULED_NEEDS_REVIEW'
    return 'NEEDS_REVIEW'

class Store:
    CURRENT_VERSION=2
    def __init__(self,path):
        self.db=sqlite3.connect(path,timeout=10);self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON');self.db.execute('PRAGMA busy_timeout=10000')
        version=self.db.execute('PRAGMA user_version').fetchone()[0]
        if version>self.CURRENT_VERSION:
            self.db.close();raise ValueError('Database is newer than this application')
        try:
            if version==0:
                self.db.executescript('BEGIN IMMEDIATE;\n'+SCHEMA+'\nPRAGMA user_version=1;\nCOMMIT;')
                version=1
            if version<2:
                # SQLite backup includes committed WAL contents, unlike a file copy.
                if str(path)!=':memory:':
                    backup=sqlite3.connect(str(path)+'.pre_v2.bak')
                    try:self.db.backup(backup)
                    finally:backup.close()
                self.db.executescript("""
BEGIN IMMEDIATE;
CREATE INDEX IF NOT EXISTS checks_cache_idx ON recovery_checks(blog_id,post_id,content_hash,engine_version);
CREATE INDEX IF NOT EXISTS versions_post_idx ON post_versions(blog_id,post_id,id);
CREATE INDEX IF NOT EXISTS google_post_idx ON google_status(blog_id,post_id,url,id);
CREATE TABLE IF NOT EXISTS task_runs(id INTEGER PRIMARY KEY,started_at TEXT,finished_at TEXT,status TEXT,task TEXT,details TEXT);
PRAGMA user_version=2;
COMMIT;
""")
            self.db.execute('PRAGMA journal_mode=WAL')
        except Exception:
            self.db.rollback();self.db.close();raise
    def close(self):self.db.close()

class Sync:
    def __init__(self,store,adapter,blog_id,progress=None,checkpoint=None,force_refresh=False):
        self.store,self.adapter,self.blog_id=store,adapter,str(blog_id)
        self.force_refresh=force_refresh
        self.progress=progress or (lambda *args:None)
        self.checkpoint=checkpoint or (lambda:None)
    def run(self):
        db=self.store.db; stamp=now()
        run_id=db.execute('INSERT INTO sync_runs(blog_id,started_at,status) VALUES(?,?,?)',(self.blog_id,stamp,'RUNNING')).lastrowid
        db.commit()
        try:
            self.checkpoint()
            if hasattr(self.adapter,'set_observer'):
                self.adapter.set_observer(self.progress,self.checkpoint)
            self.progress('Blogger 상태별 목록 조회',0,0)
            metadata=list(self.adapter.list_metadata()) # Must consume all pages before reconciliation.
            self.checkpoint()
            ids=[str(p['id']) for p in metadata]
            if len(ids)!=len(set(ids)): raise ValueError('Duplicate IDs: incomplete or inconsistent listing')
            prepared=[]; reused=0;changed_ids=set()
            for index,meta in enumerate(metadata,1):
                self.checkpoint()
                pid=str(meta['id']); status=str(meta['status']).upper(); updated=meta.get('updated')
                if status not in ('LIVE','DRAFT','SCHEDULED') or not updated: raise ValueError('Invalid metadata')
                old=db.execute('SELECT * FROM posts WHERE blog_id=? AND post_id=?',(self.blog_id,pid)).fetchone()
                metadata_matches=old is not None and all(
                    old[field]==meta[field] for field in ('title','url') if field in meta)
                if not self.force_refresh and old and old['present'] and old['updated']==updated and old['status']==status and metadata_matches:
                    reused+=1
                    self.progress('Blogger 본문 비교',index,len(metadata))
                    continue
                post=self.adapter.get_post(pid)
                self.checkpoint()
                if (str(post.get('id'))!=pid or post.get('updated')!=updated
                    or str(post.get('status','')).upper()!=status
                    or any(post.get(field,'')!=meta[field] for field in ('title','url') if field in meta)):
                    raise ValueError('Post changed during sync; retry with fresh metadata')
                post=dict(post,status=status); prepared.append(post)
                if not old or not old['present'] or old['content_hash']!=post_hash(post) or old['updated']!=post['updated'] or old['url']!=post.get('url',''):
                    changed_ids.add(pid)
                self.progress('Blogger 본문 비교',index,len(metadata))
            self.checkpoint()
            with db:
                db.execute('UPDATE posts SET present=0 WHERE blog_id=?',(self.blog_id,))
                for pid in ids: db.execute('UPDATE posts SET present=1 WHERE blog_id=? AND post_id=?',(self.blog_id,pid))
                for post in prepared:
                    h=post_hash(post); im=digest(Body(post.get('content','')).images)
                    # Unchanged reads are not an ever-growing version history.
                    if str(post['id']) in changed_ids:
                        db.execute('INSERT INTO post_versions(blog_id,post_id,captured_at,payload,content_hash) VALUES(?,?,?,?,?)',(self.blog_id,str(post['id']),stamp,json.dumps(post,ensure_ascii=False),h))
                    db.execute('INSERT OR REPLACE INTO posts VALUES(?,?,?,?,?,?,?,?,?,?,?,1)',(self.blog_id,str(post['id']),post['status'],post['updated'],post.get('title',''),post.get('url',''),post.get('content',''),h,im,anomaly(post),None))
                result={'listed':len(ids),'changed':len(changed_ids),'reused':reused}
                if self.force_refresh:result.update(refetched=len(prepared),full_test_review=True)
                db.execute('UPDATE sync_runs SET finished_at=?,status=?,details=? WHERE id=?',(now(),'DONE',json.dumps(result),run_id))
            return result
        except Exception as exc:
            with db: db.execute('UPDATE sync_runs SET finished_at=?,status=?,details=? WHERE id=?',(now(),'FAILED',str(exc),run_id))
            raise

def guard_apply(expected_hash,current_post):
    if post_hash(current_post)!=expected_hash:
        raise ValueError('LIVE 변경 감지 → 적용 중지 → 최신 글 재조회 필요')
    # This local check is not an atomic remote write. The Bridge must recheck too.
