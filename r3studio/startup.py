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
            # Exercise the packaged ImageTk path with local pixels, no network.
            import io,time
            from PIL import Image
            from .images import inspect_bytes
            output=io.BytesIO();Image.new('RGB',(1024,576),'#8090a0').save(output,format='PNG')
            pixels=output.getvalue();pixel_hash=inspect_bytes(pixels)['pixel_hash']
            cache=app.base/'image_cache';cache.mkdir(exist_ok=True)
            image_path=cache/'smoke.image';image_path.write_bytes(pixels)
            html='<p>본문 시작</p><figure><img src="https://lh3.googleusercontent.com/smoke" alt="하부 점검 사진"><figcaption>그림 1. 실제 점검 모습을 설명합니다.</figcaption></figure><p>본문 끝</p>'
            dialog=app.show_repair({'status':'HOLD','before':{'content':html},'proposed_content':html,'proposal_id':0,
                'image_review':{'items':[{'index':1,'url':'https://lh3.googleusercontent.com/smoke','preview_file':str(image_path),'pixel_hash':pixel_hash}]}})
            deadline=time.monotonic()+5
            while not dialog.preview_image_refs and time.monotonic()<deadline:
                root.update();time.sleep(0.02)
            if len(dialog.preview_image_refs)!=1:raise RuntimeError('수정안 비교 이미지 표시 실패')
            if len(dialog.preview_widgets)!=2 or any('ALT: 하부 점검 사진' not in w.get('1.0','end') or '그림 설명: 그림 1.' not in w.get('1.0','end') for w in dialog.preview_widgets):raise RuntimeError('수정안 비교 ALT·설명 표시 실패')
            dialog.destroy()
            # Check image-control tabs and retain photos across both previews.
            candidate={'result':'PASS','file':str(image_path),'info':inspect_bytes(pixels),'alt':'새 후보의 하부 점검 사진','caption':'새 후보의 실제 점검 장면을 설명합니다.'}
            dialog=app.show_repair({'status':'HOLD','before':{'content':html},'proposed_content':html,'proposal_id':0,
                'image_review':{'items':[{'index':1,'url':'https://lh3.googleusercontent.com/smoke','preview_file':str(image_path),'pixel_hash':pixel_hash}]},
                'image_edit_candidates':{'1':candidate},'image_choices':{'1':{'candidate':candidate,'expected_url':'https://lh3.googleusercontent.com/smoke','mode':'replace'}}})
            deadline=time.monotonic()+5
            while len(dialog.preview_image_refs)<2 and time.monotonic()<deadline:
                root.update();time.sleep(0.02)
            if len(dialog.preview_image_refs)<2 or len(dialog.preview_widgets)!=4:raise RuntimeError('이미지 수정 후보 탭·사진 유지 실패')
            if '선택한 후보' not in dialog.preview_widgets[1].get('1.0','end'):raise RuntimeError('미반영 이미지 후보 상태 표시 실패')
            html2=html+'<figure><img src="https://lh3.googleusercontent.com/smoke2" alt="두 번째 이미지"><figcaption>그림 2. 두 번째 장면입니다.</figcaption></figure>'
            output2=io.BytesIO();Image.new('RGB',(1024,576),'blue').save(output2,format='PNG')
            path2=cache/'smoke2.image';path2.write_bytes(output2.getvalue())
            reviews2=[{'index':1,'url':'https://lh3.googleusercontent.com/smoke','preview_file':str(image_path),'pixel_hash':pixel_hash},{'index':2,'url':'https://lh3.googleusercontent.com/smoke2','preview_file':str(path2),'pixel_hash':inspect_bytes(output2.getvalue())['pixel_hash']}]
            app.show_repair({'status':'HOLD','before':{'content':html2},'proposed_content':html2,'proposal_id':0,'image_review':{'items':reviews2}})
            editor=dialog.image_editor;editor.deiconify();root.update()
            editor.image_slot.set(2)
            def select_second(widget):
                for child in widget.winfo_children():
                    if child.winfo_class()=='TCombobox':child.event_generate('<<ComboboxSelected>>')
                    select_second(child)
            select_second(editor);root.update()
            if not dialog.winfo_viewable() or not editor.winfo_viewable():raise RuntimeError('비교창·별도 이미지 수정창 동시 표시 실패')
            calls=[];app.start_ai=lambda action,value:calls.append((action,value))
            from tkinter import ttk
            def find_button(widget,label):
                for child in widget.winfo_children():
                    if isinstance(child,ttk.Button) and child.cget('text')==label:return child
                    found=find_button(child,label)
                    if found:return found
            find_button(editor,'ALT·그림 설명 재생성').invoke()
            if calls!=[('repair_alt',{'proposal_id':0,'slot':2})] or not dialog.winfo_exists():raise RuntimeError('이미지 작업 시작 시 비교창 보존 실패')
            refreshed=app.show_repair({'status':'HOLD','before':{'content':html2},'proposed_content':html2,'proposal_id':0,'image_review':{'items':reviews2}})
            if refreshed is not dialog or refreshed.image_editor is not editor or editor.state()=='withdrawn' or editor.image_slot.get()!=2:raise RuntimeError('작업 결과 동일 창 갱신 실패')
            calls.clear()
            from unittest.mock import patch
            with patch('r3studio.app.simpledialog.askstring',return_value='청소기 안전 점검 새 주제'):
                find_button(dialog,'본문·이미지 전체 새로 만들기').invoke()
            if calls!=[('replace_all',{'proposal_id':0,'topic':'청소기 안전 점검 새 주제'})] or not dialog.winfo_exists():raise RuntimeError('전체 교체 버튼·원본 비교창 유지 실패')
            editor.destroy();dialog.destroy()
            # Failed replacement must show the requested title and resume action,
            # never an empty article comparison or the old title as the new one.
            result={'proposal_id':71,'status':'HOLD','mode':'REPLACEMENT','before':{'id':'1536421547122726881','title':'기존 모터 원리','content':html},'replacement_topic':'로봇청소기가 문턱에서 멈출 때 안전하게 점검하는 방법','replacement_job_id':7,'replacement_stage':'Evidence 원문 확인','reason':'근거 자료 확인 보류'}
            held=app.show_repair(result);root.update_idletasks()
            # ScrolledText is wrapped in a frame; inspect through descendants.
            def all_text(widget):
                return ''.join((child.get('1.0','end') if isinstance(child,tk.Text) else '')+all_text(child) for child in widget.winfo_children())
            content=all_text(held)
            if result['replacement_topic'] not in content or 'Evidence 원문 확인' not in content or '근거 자료 확인 보류' not in content:raise RuntimeError('전체 교체 보류 원인/입력 제목 표시 실패')
            if '새 제목: 기존 모터 원리' in content or hasattr(held,'preview_widgets'):raise RuntimeError('빈 수정안 비교 표시 차단 실패')
            calls.clear();find_button(held,'같은 작업 이어서 진행').invoke()
            if calls!=[('replace_resume',{'proposal_id':71})]:raise RuntimeError('같은 교체 작업 재개 실패')
            result.update(proposed_title=result['replacement_topic'],proposed_content='<h2>안전 점검</h2><p>전원을 끄고 확인합니다.</p>')
            compared=app.show_repair(result);root.update_idletasks()
            if held.winfo_exists() or not compared.preview_widgets or '전원을 끄고 확인합니다.' not in compared.preview_widgets[1].get('1.0','end'):raise RuntimeError('부분 본문 비교·보류창 종료 실패')
            compared.destroy()
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

