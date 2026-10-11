"""Cooperative cancellation: stop before next step, never abort in-flight writes."""
import threading
from .sync import now
class Cancelled(RuntimeError):pass
class Cancellation:
    def __init__(self):self.event=threading.Event()
    def request(self):self.event.set()
    def checkpoint(self):
        if self.event.is_set():raise Cancelled('사용자 중단 요청: 완료된 단계는 저장되어 있습니다.')
class TaskLog:
    def __init__(self,store,name):
        self.store=store
        with store.db:self.id=store.db.execute('INSERT INTO task_runs(started_at,status,task,details) VALUES(?,?,?,?)',(now(),'RUNNING',name,'')).lastrowid
    def finish(self,status,details=''):
        if status not in ('COMPLETED','FAILED','CANCELLED','HOLD'):raise ValueError('허용되지 않은 작업 종료 상태')
        with self.store.db:self.store.db.execute('UPDATE task_runs SET finished_at=?,status=?,details=? WHERE id=?',(now(),status,details,self.id))

def finish_validation(task,result):
    """A completed worker is not necessarily a completed validation."""
    import json
    if result.get('status')=='PASS':task.finish('COMPLETED');return
    detail=dict(result.get('error_diagnostic') or {})
    detail.setdefault('reason','VALIDATION_HOLD')
    detail.setdefault('stage','수정안 최종 검증')
    detail.setdefault('action','기존 본문·이미지를 보존하고 표시된 보류 원인을 확인하세요.')
    detail['summary']=result.get('reason') or '수정안 최종 검증 미완료'
    task.finish('HOLD',json.dumps(detail,ensure_ascii=False))

def finish_error(task,error):
    # Only our classified AI diagnostics are safe to persist.
    from .ai import AIError
    from .bridge import BridgeError
    from .evidence import EvidenceHold
    import json
    details=json.dumps(error.diagnostic,ensure_ascii=False) if isinstance(error,(AIError,BridgeError,EvidenceHold)) and error.diagnostic else type(error).__name__
    if task:task.finish('CANCELLED' if isinstance(error,Cancelled) else 'FAILED',details)
