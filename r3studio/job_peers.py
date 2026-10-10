"""Scope replacement alternatives to one post without relaxing new-post history."""
import json
from .images import ImageHold

VERSION='R3.0-job-peers-72'

def comparison_jobs(store,blog_id,job_id=None,target=None):
    rows=[dict(r) for r in store.db.execute('SELECT * FROM generation_jobs WHERE blog_id=? ORDER BY id',(str(blog_id),)) if r['id']!=job_id]
    if target is None:return rows
    from .replacement import replacement_target
    # Only a real, validated replacement request can invoke this exception.
    replacement_target(store,str(blog_id),{'replacement_target':target})
    current=store.db.execute('SELECT status FROM repair_proposals WHERE id=? AND blog_id=?',(target['proposal_id'],str(blog_id))).fetchone()
    if current['status'] not in ('HOLD','PASS'):raise ImageHold('전체 교체 적용 진행 또는 결과 확인 필요: 새 생성 중지')
    result=[]
    for row in rows:
        try:
            payload=json.loads(row['payload'])
            if not isinstance(payload,dict):raise ValueError('잘못된 작업 기록')
            prior=replacement_target(store,str(blog_id),payload)
            if prior and prior['post_id']==target['post_id']:
                proposal=store.db.execute('SELECT status,payload FROM repair_proposals WHERE id=? AND blog_id=?',(prior['proposal_id'],str(blog_id))).fetchone()
                p=json.loads(proposal['payload'])
                # APPLYING/uncertain/APPLIED work remains protected. Corrupt or
                # unbound records are retained, never silently exempted.
                if (row['status'] in ('HOLD','RUNNING','PASS') and proposal['status'] in ('HOLD','PASS')
                    and type(p.get('replacement_job_id')) is int and p['replacement_job_id']==row['id']):continue
        except (ValueError,TypeError,KeyError,ImageHold):pass
        result.append(row)
    return result
