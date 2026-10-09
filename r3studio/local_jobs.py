"""Inspect saved jobs without account settings, sync, AI, or network."""
import json

def read_jobs(store,job_id=None):
    if not store.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='generation_jobs'").fetchone():
        if job_id is not None:raise ValueError('저장된 생성 작업이 없습니다.')
        return []
    if job_id is None:
        return [dict(row,local_only=True) for row in store.db.execute('SELECT id,blog_id,topic,title,stage,status,updated_at FROM generation_jobs WHERE status IN ("HOLD","RUNNING") ORDER BY id DESC')]
    row=store.db.execute('SELECT * FROM generation_jobs WHERE id=?',(job_id,)).fetchone()
    if not row:raise ValueError('해당 작업 번호의 저장 기록이 없습니다.')
    result=dict(row);result['payload']=json.loads(result['payload']);result['local_only']=True
    return result
