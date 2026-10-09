"""Final article gate. PASS requires current text, image, link and evidence checks."""
import json
import re
from dataclasses import asdict
from .gates import fast_check,Document
from .deep import evaluate
from .evidence import validate_pack
from .sync import digest,now
from .links import check_links

class FinalHold(RuntimeError):pass
GATE_VERSION='R3.0-final-0.21'

def decide(ai,payload,live_posts,base_url,public_images,fetch):
    content=payload.get('composed_content','');title=payload.get('title','')
    if not content or not title:raise FinalHold('최종 본문 또는 제목 없음')
    validate_pack(payload.get('evidence'))
    description=payload.get('search_description')
    if not isinstance(description,str) or not 1<=len(description)<=150:raise FinalHold('검색설명 누락 또는 길이 오류')
    doc=Document(content)
    if len(doc.images)!=2 or len(public_images)!=2:raise FinalHold('검증된 공개 이미지 2장 필요')
    for image,check in zip(doc.images,public_images):
        if check.get('result')!='PASS' or check.get('url')!=image.get('src') or check.get('alt')!=image.get('alt') or check.get('article_hash')!=digest({'title':title,'content':content}):
            raise FinalHold('공개 이미지/ALT 검사 누락 또는 본문 변경')
    if re.search(r'(?:^|>)[\s]*(?:주제|본문|Pillar|Cluster|제목)\s*:',content,re.I):raise FinalHold('공개 본문에 내부 메타데이터 발견')
    links=check_links(content,base_url,live_posts,payload['evidence'],fetch)
    post={'id':'NEW','title':title,'content':content,'status':'DRAFT','url':base_url}
    fast=fast_check(post,live_posts)
    if fast.issues:raise FinalHold('최종 형식 검사: '+' / '.join(fast.issues))
    if not payload.get('independent_fact_search',{}).get('citations'):raise FinalHold('독립 Fact 검색 근거 없음')
    # Fresh search result must bind to this exact final article hash.
    if payload.get('final_fact_article_hash')!=digest({'title':title,'content':content}):raise FinalHold('최종 본문에 대한 독립 Fact 검색 필요')
    post['independent_fact_search']=payload['independent_fact_search']
    deep=evaluate(ai,post,payload['evidence'],asdict(fast))
    if deep.get('text_verified') is not True:raise FinalHold('최종 Fact/Safety/Quality 미통과')
    return {'grade':'PASS','gate_version':GATE_VERSION,'evidence_hash':digest(payload['evidence']),'metadata_hash':digest({'labels':payload.get('labels',[]),'search_description':description}),'checked_at':now(),'corpus_hash':corpus_hash(live_posts),'article_hash':digest({'title':title,'content':content}),'links':links,'deep':deep,'public_images':public_images}

def corpus_hash(posts):
    return digest(sorted((str(p['post_id']),p['status'],p.get('url',''),p.get('title',''),digest(p.get('content',''))) for p in posts))

def existing_review_hash(posts,pid):
    # The inspected post and published peers affect factual/duplicate/link review.
    # Unpublished unrelated edits cannot invalidate a published peer's review.
    return corpus_hash([p for p in posts if p['status']=='LIVE' or str(p['post_id'])==str(pid)])
