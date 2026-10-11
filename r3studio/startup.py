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
            if 'Dev81 시험판' not in root.title():raise RuntimeError('시험판 버전 표시 실패')
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
            app.new_task();app.busy=True;app.update_progress('근거 장부 작성 · AI 응답 대기 중')
            app.finish_progress(('repair_ready',{'status':'HOLD','reason':'핵심 근거 보완 필요'}))
            if '응답 대기' in app.inspection_log.get('1.0','end'):raise RuntimeError('종료 후 AI 대기 표시 제거 실패')
            if app.busy or not app.elapsed_text.get().startswith('보류 종료'):raise RuntimeError('보류 종료 표시 실패')
            app.refresh_elapsed()
            if not app.elapsed_text.get().startswith('보류 종료'):raise RuntimeError('종료 상태 유지 실패')
            app.new_task()
            if app.inspection_log.get('1.0','end').strip() or app.waiting_line is not None:raise RuntimeError('새 작업 진행 표시 초기화 실패')
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
            if held.state()!='withdrawn':raise RuntimeError('재시도 중 이전 보류창 숨김 실패')
            if app.show_repair(result) is not held or held.state()=='withdrawn':raise RuntimeError('재시도 결과 보류창 갱신 실패')
            result.update(proposed_title=result['replacement_topic'],proposed_content='<h2>안전 점검</h2><p>전원을 끄고 확인합니다.</p>')
            compared=app.show_repair(result);root.update_idletasks()
            if held.winfo_exists() or not compared.preview_widgets or '전원을 끄고 확인합니다.' not in compared.preview_widgets[1].get('1.0','end'):raise RuntimeError('부분 본문 비교·보류창 종료 실패')
            compared.destroy()
            # Exercise the new policy inside each frozen executable without AI
            # or network, including preservation of ordinary topic exclusion.
            from .sync import Store,post_hash
            from .recovery import Recovery
            from .generation import Generation
            from .job_peers import comparison_jobs
            from .evidence import EvidenceHold
            db=Store(str(Path(folder)/'job-policy.sqlite3'))
            try:
                Recovery(db,None,None);g=Generation(db,None,'SMOKE')
                before={'id':'1','title':'기존 글','content':'<p>기존 본문</p>','status':'SCHEDULED'}
                records=[]
                for topic in ('로봇청소기 문턱 안전 점검 방법','로봇청소기 문턱 안전 점검 방법 상세 안내'):
                    p={'mode':'REPLACEMENT','before':before,'expected_hash':post_hash(before)}
                    with db.db:pid=db.db.execute('INSERT INTO repair_proposals(blog_id,post_id,created_at,status,payload) VALUES(?,?,?,?,?)',('SMOKE','1',now(),'HOLD',json.dumps(p))).lastrowid
                    target={'proposal_id':pid,'blog_id':'SMOKE','post_id':'1','expected_hash':p['expected_hash']}
                    job=g.reserve(topic,target=target);p['replacement_job_id']=job
                    with db.db:db.db.execute('UPDATE repair_proposals SET payload=? WHERE id=?',(json.dumps(p),pid))
                    g.save(job,'Evidence','HOLD',{'topic':topic,'replacement_target':target});records.append((pid,job,target))
                if comparison_jobs(db,'SMOKE',records[1][1],records[1][2]):raise RuntimeError('같은 대상 미적용 교체안 차단 해제 실패')
                try:g.reserve('로봇청소기 문턱 안전 점검 방법')
                except EvidenceHold:pass
                else:raise RuntimeError('일반 새 글 주제 중복 보호 실패')
                with db.db:db.db.execute('UPDATE repair_proposals SET status="APPLIED" WHERE id=?',(records[0][0],))
                if [r['id'] for r in comparison_jobs(db,'SMOKE',records[1][1],records[1][2])]!=[records[0][1]]:raise RuntimeError('적용 기록 비교 보호 실패')
            finally:db.close()
            # The reported last-search failure must execute a real ledger repair
            # in each frozen executable. No credentials or network are used.
            from .evidence import Research
            from copy import deepcopy
            evidence={'sources':[{'id':'a','url':'https://manufacturer.example/manual','grade':'A'},{'id':'b','url':'https://agency.example/guide','grade':'A'}],
                      'facts':[{'id':str(i),'text':'공식 안전 점검 조건 '+str(i),'source_ids':['a' if i%2 else 'b'],'core':i<2,'kind':['core','core','practical','condition'][i]} for i in range(4)]}
            class LedgerAI:
                searches=0;ledgers=0
                def ask(self,*args,**kwargs):
                    self.searches+=1;return {'citations':[{'url':source['url']} for source in evidence['sources']]}
                def object(self,prompt):
                    self.ledgers+=1;value=deepcopy(evidence)
                    if self.ledgers<4:
                        for fact in value['facts']:fact['core']=False
                    if self.ledgers==1:value['facts'][2]['kind']='other'
                    if self.ledgers==2:value['facts']=value['facts'][:2]+value['facts'][3:]
                    return value
            ledger_ai=LedgerAI();checked=Research(ledger_ai).collect('안전 점검','안전 점검')
            if (ledger_ai.searches,ledger_ai.ledgers)!=(3,4) or checked['research_budget']['ledger_repairs']!=1:raise RuntimeError('마지막 검색 이후 장부 보완 실행 실패')
            if checked['research_attempts'][-1].get('recovery_state')!='EXECUTED':raise RuntimeError('실제 복구 실행 기록 실패')
            # Verify the new generation-only recovery in each frozen executable.
            from .generation_evidence import prepare,writer_context
            from .sync import digest
            quote='제품 설명서를 확인하고 지정된 안전 점검 조건과 사용 지침을 따릅니다.'
            unsupported=deepcopy(evidence)
            for fact in unsupported['facts']:fact['text']='근거 없는 모터 고장 단정 '+fact['id']
            class OriginalReader:
                calls=0
                def read_many(self,sources,progress):
                    self.calls+=1
                    return {s['id']:{'status':'FETCHED','text':quote,'text_hash':digest(quote),'final_url':s['url']} for s in sources}
            class OriginalAI:
                refills=0
                def object(self,prompt):
                    if 'R3 GENERATION ORIGINAL REFILL' in prompt:
                        self.refills+=1;value=deepcopy(evidence)
                        for fact in value['facts']:fact['text']=quote+' '+fact['id']
                        return {'facts':value['facts']}
                    data=json.loads(prompt.split('\n',1)[1])
                    return {'sources':[{'source_id':s['id'],'grade':'A','publisher':s['id']} for s in data['sources']],
                            'claims':[{'fact_id':f['id'],'source_id':f['source_ids'][0],'quote':quote,'supported':f['text'].startswith(quote)} for f in data['facts']]}
            original_ai=OriginalAI();original_reader=OriginalReader();refilled=prepare(original_ai,unsupported,original_reader,'안전 점검','안전 점검')
            if original_ai.refills!=1 or original_reader.calls!=1 or '근거 없는' in json.dumps(writer_context('안전 점검','안전 점검',refilled),ensure_ascii=False):raise RuntimeError('원문 기반 새 글 근거 재구성 실패')
            # Exercise the real JSON client/schema/retry path in each frozen EXE.
            from .ai import Gemini
            from .origin_response import request_review,SCHEMA
            calls=[]
            context={'facts':refilled['facts'],'sources':refilled['sources'],'originals':refilled['original_verification']['originals']}
            def format_transport(payload):
                calls.append(payload)
                value={'claims':{}} if len(calls)==1 else original_ai.object('claims:[{fact_id\n'+json.dumps(context,ensure_ascii=False))
                return {'outputs':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}]}
            response,trace=request_review(Gemini('local-smoke-test-only','mock',format_transport),context)
            if len(calls)!=2 or trace[-1]['state']!='VALID_SHAPE' or any(c['response_format']['schema']!=SCHEMA for c in calls):raise RuntimeError('원문 검사 필수 스키마·형식 재검사 실패')
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

