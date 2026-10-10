"""Windowed startup, safe diagnostics, and a per-user single-instance lock."""
import json
import os
import platform
import sys
import traceback
from pathlib import Path
from .sync import now

def data_directory():
    base=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'R3_Blogger_Studio'
    base.mkdir(parents=True,exist_ok=True)
    return base

class AlreadyRunning(RuntimeError):pass

class InstanceLock:
    def __init__(self,path):self.path=Path(path);self.file=None
    def acquire(self):
        self.file=self.path.open('a+b')
        self.file.seek(0,2)
        if self.file.tell()==0:self.file.write(b'0');self.file.flush()
        self.file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close();self.file=None
            raise AlreadyRunning('프로그램이 이미 실행 중입니다.') from None
        return self
    def release(self):
        if self.file is not None:self.file.close();self.file=None
    def __enter__(self):return self.acquire()
    def __exit__(self,*args):self.release()

def record_failure(base,error,tb=None):
    # Do not store exception text, source lines, locals, environment, or HTTP payloads.
    frames=traceback.extract_tb(tb if tb is not None else error.__traceback__)
    entry={'time':now(),'error_type':type(error).__name__,
           'frames':[{'file':Path(f.filename).name,'function':f.name,'line':f.lineno} for f in frames]}
    folder=Path(base)/'diagnostics';folder.mkdir(parents=True,exist_ok=True)
    target=folder/'errors.jsonl'
    if target.exists() and target.stat().st_size>1024*1024:
        target.replace(folder/'errors.previous.jsonl')
    with target.open('a',encoding='utf-8') as out:out.write(json.dumps(entry,ensure_ascii=False)+'\n')
    return target

def diagnostic_summary():
    from importlib.metadata import version,PackageNotFoundError
    try:pillow=version('Pillow')
    except PackageNotFoundError:pillow='미설치'
    return {'program':'R3.0 개발본','python':platform.python_version(),'system':platform.system(),
            'architecture':platform.machine(),'pillow':pillow,'frozen':bool(getattr(sys,'frozen',False))}

def smoke_test():
    """Construct the packaged UI and round-trip DPAPI; no account/network calls."""
    import tempfile
    import tkinter as tk
    from .settings import Settings,FIELDS
    from .app import App
    environment_keys=set(FIELDS)|{'LOCALAPPDATA'}
    previous={k:os.environ.get(k) for k in environment_keys}
    root=None
    try:
        with tempfile.TemporaryDirectory(prefix='r3-smoke-') as folder:
            for key in FIELDS:os.environ.pop(key,None)
            os.environ['LOCALAPPDATA']=folder
            root=tk.Tk();root.withdraw()
            app=App(root)
            root.update_idletasks() # No scheduled startup/network callbacks.
            if len(app.tabs.tabs())!=3:raise RuntimeError('세 메뉴 화면 구성 실패')
            if len(app.inspect_panes.panes())!=2:raise RuntimeError('목록·상세 조절 창 구성 실패')
            root.deiconify();root.update();root.update_idletasks()
            target=max(10,min(180,app.inspect_panes.winfo_height()//2))
            app.inspect_panes.sashpos(0,target)
            if app.inspect_panes.sashpos(0)!=target:raise RuntimeError(f'목록·상세 경계선 조절 실패: height={app.inspect_panes.winfo_height()}, requested={target}, actual={app.inspect_panes.sashpos(0)}')
            app.update_progress('근거 조사 · AI 응답 대기 중')
            if str(app.progress_bar.cget('mode'))!='determinate':raise RuntimeError('AI 대기 진행 표시 실패')
            position=float(app.progress_bar.cget('value'));app.set_status('오류 정지 표시 시험')
            if float(app.progress_bar.cget('value'))!=position:raise RuntimeError('정지 후 진행 위치 보존 실패')
            if app.busy:raise RuntimeError('기본 자동 조회 비활성화 실패')
            settings=Settings(Path(folder)/'smoke-settings.json')
            settings.save({'R3_BRIDGE_SECRET':'local-smoke-test-only','R3_START_MODE':'DEMO'})
            if settings.load().get('R3_BRIDGE_SECRET')!='local-smoke-test-only':raise RuntimeError('DPAPI 복호화 시험 실패')
            root.destroy();root=None
        return 0
    except Exception as error:
        if sys.stderr is not None:print('Smoke test failed: '+type(error).__name__+': '+str(error),file=sys.stderr)
        return 1
    finally:
        if root is not None:
            try:root.destroy()
            except tk.TclError:pass
        for key,value in previous.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value

def launch(diagnostic=False,app_factory=None,root_factory=None):
    import tkinter as tk
    from tkinter import messagebox
    root=None;lock=None;base=data_directory()
    def notify(kind,title,text,parent=None):
        # If Tk itself cannot initialize, the saved diagnostics remain available.
        try:getattr(messagebox,kind)(title,text,parent=parent)
        except tk.TclError:pass
    if diagnostic and sys.stdout is not None:print(json.dumps(diagnostic_summary(),ensure_ascii=False,indent=2))
    try:
        lock=InstanceLock(base/'studio.lock').acquire()
        from .backups import daily_snapshots
        daily_snapshots(base)
        root=(root_factory or tk.Tk)()
        def report(exc_type,error,tb):
            record_failure(base,error,tb)
            notify('showerror','R3.0','화면 작업 중 오류가 발생했습니다. 작업 기록과 진단 기록을 확인하세요.',parent=root)
        root.report_callback_exception=report
        if app_factory is None:
            from .app import App
            app_factory=App
        app_factory(root);root.mainloop()
        return 0
    except AlreadyRunning:
        notify('showinfo','R3.0','이미 열린 R3.0 창을 사용하세요.')
        return 2
    except Exception as error:
        path=record_failure(base,error)
        notify('showerror','R3.0 실행 오류','프로그램을 열지 못했습니다. 진단 모드에서 환경을 확인하세요.\n진단 기록: '+str(path),parent=root)
        return 1
    finally:
        if root is not None:
            try:root.destroy()
            except tk.TclError:pass
        if lock:lock.release()
