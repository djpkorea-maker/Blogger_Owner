"""Grounded evidence ledger. Source count alone does not establish correctness."""
import json
from urllib.parse import urlparse
from .sync import digest,now

class EvidenceHold(RuntimeError):
    def __init__(self,message,attempts=None):super().__init__(message);self.attempts=attempts

def validate_pack(pack):
    if not isinstance(pack,dict): raise EvidenceHold('근거 자료 형식 오류')
    sources=pack.get('sources',[]); facts=pack.get('facts',[])
    if not isinstance(sources,list) or not isinstance(facts,list): raise EvidenceHold('근거 자료 형식 오류')
    if any(not isinstance(s,dict) or not isinstance(s.get('id'),str) or not isinstance(s.get('url'),str) for s in sources): raise EvidenceHold('출처 형식 오류')
    if len({s['id'] for s in sources})!=len(sources): raise EvidenceHold('중복 출처 ID')
    for source in sources:
        try:parsed=urlparse(source['url']);valid=parsed.scheme=='https' and bool(parsed.hostname) and not parsed.username and not parsed.password
        except ValueError:valid=False
        if not valid or not source['id'].strip() or source.get('grade') not in ('A','B','C'):raise EvidenceHold('출처 주소 또는 등급 형식 오류')
    if any(not isinstance(f,dict) or not isinstance(f.get('id'),str) or not isinstance(f.get('text'),str) or not isinstance(f.get('source_ids'),list) or any(not isinstance(x,str) for x in f['source_ids']) for f in facts): raise EvidenceHold('사실 근거 형식 오류')
    if len({f['id'] for f in facts})!=len(facts):raise EvidenceHold('중복 사실 ID')
    if any(not f['id'].strip() or not f['text'].strip() or f.get('kind') not in ('core','practical','condition','other') or type(f.get('core',False)) is not bool for f in facts):raise EvidenceHold('사실 내용 또는 분류 형식 오류')
    source_ids={s.get('id') for s in sources if s.get('url','').startswith('https://') and s.get('grade') in ('A','B')}
    domains={urlparse(s['url']).hostname for s in sources if s.get('id') in source_ids}
    supported=[f for f in facts if f.get('text') and f.get('source_ids') and set(f['source_ids'])<=source_ids]
    issues=[]
    if len(domains)<2: issues.append('독립 A/B 출처 2개 미만')
    if len(supported)<4: issues.append('근거 연결 사실 4개 미만')
    if sum(f.get('core') is True for f in supported)<2: issues.append('핵심 근거 2개 미만')
    if not any(f.get('kind')=='practical' for f in supported): issues.append('실제 확인·활용 근거 부족')
    if not any(f.get('kind')=='condition' for f in supported): issues.append('조건·예외 근거 부족')
    if issues: raise EvidenceHold(' / '.join(issues))
    return digest(pack)

class Research:
    def __init__(self,ai): self.ai=ai
    def collect(self,title,topic,progress=lambda *args:None):
        collected=[]; notes=[];trace=[];search_needed=True
        for attempt in range(3):
            progress('Evidence 조사',attempt+1,3)
            if search_needed:
                progress('근거 검색',attempt+1,3)
                response=self.ai.ask('공식 제조사 설명서·공공기관·표준 원문 중심으로 다음 질문을 조사하세요. 추측을 제외하고 수치의 조건과 예외를 밝히세요.\n'+json.dumps({'title':title,'topic':topic,'missing':notes},ensure_ascii=False),search=True)
                if not isinstance(response,dict) or not response.get('citations'):raise EvidenceHold('RESEARCH_SYSTEM_ERROR: 실제 검색 출처 없음',trace)
                collected.append(response)
            progress('근거 장부 작성',attempt+1,3)
            pack=self.ai.object('아래 검색 결과만 사용하여 근거 장부를 만드세요. sources:[{id,url,grade:A|B|C,reason}], facts:[{id,text,source_ids,core:boolean,kind:core|practical|condition|other}]. A는 공식 원문, B는 신뢰할 수 있는 전문자료입니다. 출처 등급을 부풀리지 마세요.\n'+json.dumps({'search_results':collected,'correction':notes},ensure_ascii=False))
            try:
                validate_pack(pack)
            except EvidenceHold as exc:
                notes=[str(exc)];trace.append({'attempt':attempt+1,'reason':str(exc)})
                search_needed='형식' not in str(exc);continue
            pack.pop('original_verification',None) # Never trust a verification stamp produced by the model.
            actual={c['url'] for r in collected for c in r['citations'] if isinstance(c,dict) and isinstance(c.get('url'),str)}
            if any(s['url'] not in actual for s in pack['sources']):raise EvidenceHold('검색 결과 밖의 출처 생성 감지',trace)
            pack['retrieved_at']=now();pack['grounding']=collected;pack['research_attempts']=trace;return pack
        raise EvidenceHold('Evidence 보강 2회 후에도 부족: '+' / '.join(notes),trace)

def collect_cached(store,ai,title,topic,scope,progress=lambda *args:None,max_age_hours=168):
    from datetime import datetime,timezone
    db=store.db
    db.execute('CREATE TABLE IF NOT EXISTS evidence_packs(cache_key TEXT PRIMARY KEY,created_at TEXT,payload TEXT)'); db.commit()
    key=digest({'title':title,'topic':topic,'scope':scope,'model':ai.model,'version':'evidence-0.20'})
    old=db.execute('SELECT * FROM evidence_packs WHERE cache_key=?',(key,)).fetchone()
    if old:
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(old['created_at'])).total_seconds()/3600
        if 0<=age<max_age_hours:
            progress('기존 근거 재사용',1,1)
            pack=json.loads(old['payload']);validate_pack(pack);return pack
    pack=Research(ai).collect(title,topic,progress)
    from .sources import SourceReader,verify_origins
    pack=verify_origins(ai,pack,SourceReader(store),progress)
    with db: db.execute('INSERT OR REPLACE INTO evidence_packs VALUES(?,?,?)',(key,now(),json.dumps(pack,ensure_ascii=False)))
    return pack
