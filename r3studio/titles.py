"""Bounded title refill; only rejected title candidates are regenerated."""
import json
from .gates import normalize,shingles
from .evidence import EvidenceHold

def title_issue(title,existing):
    if not isinstance(title,str) or not title.strip():return '제목 누락'
    title=title.strip()
    if not 8<=len(title)<=100 or '\n' in title or '<' in title or '>' in title:return '제목 길이 또는 형식 오류'
    candidate=shingles(title)
    for prior in existing:
        if normalize(title)==normalize(prior):return '기존 제목과 동일'
        other=shingles(prior)
        if len(candidate)>=8 and len(candidate & other)/max(1,min(len(candidate),len(other)))>=0.8:return '기존 제목과 높은 기본 유사도'
    return None

def refill(ai,topic,existing,record=lambda *args:None,validator=None):
    reasons=[]
    for attempt in range(1,4):
        response=ai.object('실제 독자 질문을 해결하는 구체적인 제목 하나를 정하세요. title:문자열. 과장·HTML 금지. 8~100자. 기존 제목과 같은 질문을 반복하지 마세요.\n'+json.dumps({'topic':topic,'existing_titles':existing,'rejected':reasons},ensure_ascii=False))
        title=response.get('title') if isinstance(response,dict) else None
        issue=title_issue(title,existing)
        if not issue and validator is not None:
            issue=validator(title.strip())
        record(attempt,title,issue)
        if not issue:return title.strip()
        reasons.append({'title':title if isinstance(title,str) else None,'reason':issue})
    raise EvidenceHold('제목 보완 3회 후에도 미통과: '+reasons[-1]['reason'])
