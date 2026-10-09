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
        if status not in ('COMPLETED','FAILED','CANCELLED'):raise ValueError('허용되지 않은 작업 종료 상태')
        with self.store.db:self.store.db.execute('UPDATE task_runs SET finished_at=?,status=?,details=? WHERE id=?',(now(),status,details,self.id))

def finish_error(task,error):
    # Persist the exception class only, never remote payloads or credentials.
    if task:task.finish('CANCELLED' if isinstance(error,Cancelled) else 'FAILED',type(error).__name__)
