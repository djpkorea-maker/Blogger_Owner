"""References bind a visible article excerpt to an original-backed ledger fact."""
import html,re,json
from urllib.parse import urlparse
from .sync import digest
from .sources import require_originals,norm
from .evidence import EvidenceHold

def candidates(pack):
    require_originals(pack)
    claims=pack['original_verification']['claims']
    used={c['source_id'] for c in claims}
    return [s for s in pack['sources'] if s['id'] in used and s['grade'] in ('A','B')]

def document_label(source,pack):
    original=pack['original_verification']['originals'].get(source['id'],{})
    # Prefer title captured from the fetched document. A domain/path is honest
    # when no title was available; never publish an internal grading reason.
    title=original.get('document_title','')
    if isinstance(title,str) and title.strip():return norm(title)[:180]
    parsed=urlparse(source['url'])
    return (parsed.hostname or '')+(parsed.path or '/')[:140]

def select(choice,content,pack):
    refs=choice.get('references') if isinstance(choice,dict) else None
    if not isinstance(refs,list) or not 1<=len(refs)<=4:raise EvidenceHold('본문 출처 연결 응답 확인 필요: references 1~4개')
    from .article_policy import body_text
    actual=body_text(content);lookup={s['id']:s for s in candidates(pack)}
    facts={f['id']:f for f in pack['facts']}
    checked={(c['fact_id'],c['source_id']) for c in pack['original_verification']['claims']}
    selected=[];seen=set()
    for item in refs:
        if not isinstance(item,dict):raise EvidenceHold('본문 출처 연결 항목 형식 오류')
        sid=item.get('source_id');fid=item.get('fact_id');excerpt=item.get('excerpt')
        if (not isinstance(sid,str) or not isinstance(fid,str) or sid not in lookup or fid not in facts
            or (fid,sid) not in checked or not isinstance(excerpt,str) or not 10<=len(norm(excerpt))<=350
            or norm(excerpt).lower() not in actual):
            raise EvidenceHold('본문 구절·검증된 사실·원문 출처 연결 불일치')
        url=lookup[sid]['url']
        if url in seen:continue
        seen.add(url)
        selected.append({'source_id':sid,'fact_id':fid,'excerpt':norm(excerpt),
            'url':url,'label':document_label(lookup[sid],pack),
            'supported_fact':facts[fid]['text']})
    return selected

def reference_html(selected):
    return '<section data-r3-kind="references"><h2>참고 자료</h2><ul>'+''.join(
        '<li><a href="'+html.escape(r['url'],quote=True)+'">'+html.escape(r['label'])+
        '</a> — 본문에서 확인한 내용: '+html.escape(r['excerpt'])+'</li>' for r in selected)+'</ul></section>'

def verify_binding_content(content,binding):
    from .article_policy import body_text
    from .gates import Document
    if 'data-r3-kind="references"' not in content:return
    if (not isinstance(binding,dict) or binding.get('body_hash')!=digest(body_text(content))
        or not isinstance(binding.get('references'),list) or not binding['references']):
        raise EvidenceHold('본문 출처 연결 기록 누락 또는 본문 변경: 자료 재연결 필요')
    actual=body_text(content);links=set(Document(content).links)
    for ref in binding['references']:
        if not isinstance(ref,dict) or ref.get('url') not in links or not isinstance(ref.get('excerpt'),str) or norm(ref['excerpt']).lower() not in actual:
            raise EvidenceHold('참고 자료와 현재 본문 구절 연결 불일치')
