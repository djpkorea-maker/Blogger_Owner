"""Desktop development UI. Tk is accessed only from the main thread."""
import json
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk,messagebox,filedialog,simpledialog
from tkinter.scrolledtext import ScrolledText
from .bridge import BridgeAdapter
from .sync import Store,Sync
from .gates import run_checks

class DemoAdapter:
    def __init__(self):
        common='<h2>확인 방법</h2><p>'+('사용 전 용기 표시와 제조사 사용 설명서를 확인합니다. ' * 40)+'</p><h2>점검 순서</h2><p>'+('사용 조건에 따라 결과가 달라질 수 있습니다. '*40)+'</p>'
        common+='<img src="https://example.com/a.jpg" alt="용기"><img src="https://example.com/b.jpg" alt="표시"><a href="/related">관련 글</a><a href="https://example.org/manual">설명서</a>'
        self.posts=[{'id':'1','status':'LIVE','updated':'2026-10-09T09:00:00Z','title':'전자레인지 용기 확인 방법','content':common,'url':'https://example.com/post1'}, {'id':'2','status':'SCHEDULED','updated':'2026-10-09T09:00:00Z','title':'예약 글 검사 예시','content':'<p>검사 전 예약 글입니다.</p>','url':'https://example.com/post2'}, {'id':'3','status':'DRAFT','updated':'2026-10-09T09:00:00Z','title':'','content':'','url':''}]
    def list_metadata(self): return [{k:p[k] for k in ('id','status','updated')} for p in self.posts]
    def get_post(self,pid): return next(dict(p) for p in self.posts if p['id']==pid)

class App:
    def __init__(self,root):
        self.root=root; root.title('R3.0 Blogger 통합 스튜디오 · Dev62 시험판'); root.geometry('1080x720')
        from .tasks import Cancellation
        self.cancel_token=Cancellation()
        self.events=queue.Queue(); self.busy=False; self.demo=tk.BooleanVar(value=True)
        from .startup import data_directory
        base=data_directory()
        self.base=base
        from .settings import Settings,SettingsError
        self.settings=Settings(base/'settings.json')
        try:self.settings.activate(self.settings.load())
        except SettingsError:root.after(100,lambda:messagebox.showwarning('설정','저장된 연결 정보를 읽지 못했습니다. 설정 화면에서 다시 입력하세요.'))
        from .start_mode import demo_on_start
        self.demo.set(demo_on_start(os.environ))
        top=ttk.Frame(root,padding=12); top.pack(fill='x')
        header=ttk.Frame(top);header.pack(fill='x')
        toolbar=ttk.Frame(top)
        ttk.Label(header,text='R3.0 Blogger 통합 스튜디오',font=('',18,'bold')).pack(side='left')
        toolbar.pack(fill='x',pady=(8,0))
        ttk.Checkbutton(toolbar,text='데모 데이터 사용',variable=self.demo).pack(side='right')
        ttk.Button(toolbar,text='연결 준비 상태',command=self.show_readiness).pack(side='right',padx=5)
        ttk.Button(toolbar,text='백업 확인',command=self.show_backups).pack(side='right',padx=5)
        ttk.Button(toolbar,text='작업 기록',command=self.show_history).pack(side='right',padx=5)
        ttk.Button(toolbar,text='연결 설정',command=self.show_settings).pack(side='right',padx=10)
        ttk.Button(toolbar,text='다음 단계 전에 중단',command=self.cancel_current).pack(side='right',padx=10)
        root.protocol('WM_DELETE_WINDOW',self.close_window)
        self.status_text=tk.StringVar(value='데모 모드 · 연결 전입니다.')
        ttk.Label(root,textvariable=self.status_text,wraplength=1000,padding=8).pack(side='bottom',fill='x')
        self.tabs=ttk.Notebook(root); self.tabs.pack(fill='both',expand=True,padx=12,pady=8)
        self.inspect=ttk.Frame(self.tabs,padding=10); self.tabs.add(self.inspect,text='① 기존 블로그 글 조회/점검')
        self.new=ttk.Frame(self.tabs,padding=15); self.tabs.add(self.new,text='② 새 글 생성')
        self.google=ttk.Frame(self.tabs,padding=15); self.tabs.add(self.google,text='③ Google 상태 감시')
        ttk.Label(self.new,text='새 글 생성 · 최종 검사 PASS 후 저장·발행 가능',font=('',13)).pack(anchor='w')
        ttk.Label(self.new,text='주제를 한 줄에 하나씩 입력하세요. 기본 1개, 최대 3개입니다.').pack(anchor='w',pady=8)
        self.topics=ScrolledText(self.new,height=5); self.topics.pack(fill='x')
        self.generate_button=ttk.Button(self.new,text='근거 조사 + 글 생성 (발행 없음)',command=self.start_generation)
        self.generate_button.pack(anchor='w',pady=10)
        image_controls=ttk.Frame(self.new);image_controls.pack(fill='x')
        ttk.Label(image_controls,text='생성 작업 번호:').pack(side='left')
        self.job_id=ttk.Entry(image_controls,width=10);self.job_id.pack(side='left',padx=8)
        ttk.Button(image_controls,text='이미지 후보 2장 검사',command=self.start_image_check).pack(side='left')
        ttk.Button(image_controls,text='보류 목록',command=lambda:self.start_job_action('jobs')).pack(side='left',padx=5)
        ttk.Button(image_controls,text='작업 불러오기',command=lambda:self.start_job_action('load_job')).pack(side='left',padx=5)
        ttk.Button(image_controls,text='이어서 작성',command=lambda:self.start_job_action('resume')).pack(side='left',padx=5)
        ttk.Button(image_controls,text='최종 검사',command=lambda:self.start_job_action('finalize')).pack(side='left',padx=5)
        publication=ttk.Frame(self.new);publication.pack(fill='x',pady=8)
        ttk.Button(publication,text='이미지 자동 생성',command=lambda:self.start_job_action('generate_images')).pack(side='left')
        ttk.Button(publication,text='이미지 업로드·배치',command=lambda:self.start_job_action('upload_images')).pack(side='left',padx=5)
        ttk.Button(publication,text='PASS 글 초안 저장',command=lambda:self.start_job_action('draft')).pack(side='left',padx=5)
        ttk.Button(publication,text='PASS 글 발행',command=lambda:self.start_job_action('publish')).pack(side='left',padx=5)
        ttk.Button(publication,text='PASS 글 예약',command=lambda:self.start_job_action('schedule')).pack(side='left',padx=5)
        ttk.Button(self.new,text='이미지 업로드 결과 확인 (조회만)',command=lambda:self.start_job_action('reconcile_images')).pack(anchor='w',pady=4)
        ttk.Button(self.new,text='이전 저장 결과 재확인 (조회만)',command=lambda:self.start_job_action('reconcile')).pack(anchor='w',pady=4)
        self.generation_notes=ScrolledText(self.new,height=15,wrap='word'); self.generation_notes.pack(fill='both',expand=True)
        ttk.Label(self.google,text='공개 접근과 Google 색인 상태를 별도로 확인합니다.',font=('',13)).pack(anchor='w')
        ttk.Button(self.google,text='현재 LIVE 글 상태 확인',command=self.start_google).pack(anchor='w',pady=10)
        self.google_notes=ScrolledText(self.google,wrap='word');self.google_notes.pack(fill='both',expand=True)
        controls=ttk.Frame(self.inspect); controls.pack(fill='x')
        self.button=ttk.Button(controls,text='LIVE 동기화 + Fast 검사',command=self.start); self.button.pack(side='left')
        ttk.Label(controls,text='시험판: 매번 전체 조회·Fast 재검사').pack(side='left',padx=15)
        ttk.Button(controls,text='수정안 만들기',command=self.start_repair).pack(side='left')
        ttk.Button(controls,text='수정·복원 결과 확인',command=self.start_apply_reconcile).pack(side='left',padx=5)
        ttk.Button(controls,text='수정 백업 복원',command=self.start_rollback).pack(side='left',padx=5)
        ttk.Button(controls,text='선택 글 심층 검사',command=self.start_deep).pack(side='right')
        self.status=ttk.Label(self.inspect,textvariable=self.status_text,wraplength=1000); self.status.pack(anchor='w',pady=10)
        table_frame=ttk.Frame(self.inspect);table_frame.pack(fill='both',expand=True)
        self.table=ttk.Treeview(table_frame,columns=('state','grade','title','updated'),show='headings')
        for name,label,width in [('state','상태',110),('grade','검사 결과',220),('title','제목',430),('updated','Blogger 수정 시각',220)]:
            self.table.heading(name,text=label); self.table.column(name,width=width)
        scroll=ttk.Scrollbar(table_frame,orient='vertical',command=self.table.yview);scroll.pack(side='right',fill='y')
        self.table.config(yscrollcommand=scroll.set)
        self.table.pack(side='left',fill='both',expand=True); self.table.bind('<<TreeviewSelect>>',self.detail)
        self.notes=ScrolledText(self.inspect,height=9,wrap='word'); self.notes.pack(fill='x',pady=8)
        self.results={};self.last_apply_id=None; root.after(100,self.poll)
        root.after(300,self.start)
    def set_status(self,text):
        self.status_text.set(text)
    def sync_posts(self,store,adapter,blog_id,selected_post=None):
        def progress(stage,index,total):
            text=f'{stage} {index}/{total}' if total else f'{stage} · {index}개 확인'
            self.events.put(('progress',text))
        return Sync(store,adapter,blog_id,progress,self.cancel_token.checkpoint,force_refresh=selected_post is None,refresh_ids=() if selected_post is None else (selected_post,)).run()
    def cancel_current(self):
        if self.busy:
            self.cancel_token.request();self.set_status(text='중단 요청됨 · 진행 중인 요청 결과 확인 후 멈춥니다.')
    def close_window(self):
        if self.busy:
            self.cancel_current();messagebox.showinfo('R3.0','현재 요청 결과를 기록한 뒤 창을 닫아 주세요.');return
        self.root.destroy()
    def new_task(self):
        from .tasks import Cancellation
        self.cancel_token=Cancellation()
    def start_repair(self):
        if self.busy:return
        selected=self.table.selection()
        if not selected or self.demo.get():
            messagebox.showinfo('R3.0','실제 글을 조회하고 수정할 글을 선택하세요.');return
        self.start_ai('repair',selected[0])
    def start_apply_reconcile(self):
        if self.busy or self.demo.get():return
        audit=simpledialog.askinteger('수정 결과 확인','확인할 수정 또는 복원 기록 번호를 입력하세요.',parent=self.root)
        if audit is not None:self.start_ai('reconcile_apply',audit)
    def start_rollback(self):
        if self.busy or self.demo.get():return
        audit=simpledialog.askinteger('백업 복원','복원할 수정 기록 번호를 입력하세요.',initialvalue=self.last_apply_id,parent=self.root)
        if audit is not None:self.start_ai('rollback',audit)
    def show_publication(self,plan,description):
        dialog=tk.Toplevel(self.root);dialog.title('PASS 글 저장 계획 확인');dialog.geometry('900x650')
        mode={'DRAFT':'초안 저장','LIVE':'공개 발행','SCHEDULED':'예약 저장'}[plan['mode']]
        ttk.Label(dialog,text=mode+' · '+plan['title'],font=('',14,'bold'),wraplength=850).pack(fill='x',padx=15,pady=10)
        ttk.Label(dialog,text='블로그 ID: '+plan['blog_id']+' / 예약: '+str(plan['schedule'] or '해당 없음')+'\n라벨: '+', '.join(plan['labels'])+'\n검색설명 (로컬 검사값): '+description,wraplength=850).pack(fill='x',padx=15)
        from .gates import Document
        text=ScrolledText(dialog,wrap='word');text.pack(fill='both',expand=True,padx=15,pady=10);text.insert('end','\n'.join(Document(plan['content']).text));text.config(state='disabled')
        ttk.Label(dialog,text='실행 직전에 최신 동기화·PASS·본문·근거·시간을 다시 확인합니다. 검색설명 Blogger 저장은 검증 전입니다.',wraplength=850).pack(fill='x',padx=15)
        def execute():
            if self.busy:return
            dialog.destroy();self.start_ai('execute_plan',plan)
        ttk.Button(dialog,text='검토한 계획으로 '+mode,command=execute).pack(pady=10)
    def show_repair(self,result):
        dialog=tk.Toplevel(self.root);dialog.title('수정안 비교 · '+result['status']);dialog.geometry('1050x700')
        from .gates import Document
        panes=ttk.Panedwindow(dialog,orient='horizontal');panes.pack(fill='both',expand=True,padx=10,pady=10)
        original=result['before'].get('content','');proposed=result.get('plan',{}).get('proposal',{}).get('content','')
        for label,content in [('현재 글',original),('검증된 수정안',proposed)]:
            frame=ttk.Frame(panes);panes.add(frame,weight=1);ttk.Label(frame,text=label,font=('',13,'bold')).pack(anchor='w')
            text=ScrolledText(frame,wrap='word');text.pack(fill='both',expand=True);text.insert('end','\n'.join(Document(content).text));text.config(state='disabled')
        ttk.Label(dialog,text=result.get('reason') or '수정 이유: '+' / '.join(str(x) for x in result.get('changes',[])),wraplength=1000).pack(fill='x',padx=10,pady=8)
        def apply():dialog.destroy();self.start_ai('apply_repair',result['proposal_id'])
        ttk.Button(dialog,text='검토한 수정안 적용',command=apply,state='normal' if result['status']=='PASS' else 'disabled').pack(pady=10)
    def show_backups(self):
        if self.busy:return
        from .backups import inventory,inventory_text
        dialog=tk.Toplevel(self.root);dialog.title('일일 기록 백업 확인');dialog.geometry('850x550')
        text=ScrolledText(dialog,wrap='word');text.pack(fill='both',expand=True,padx=10,pady=10)
        text.insert('end',inventory_text(inventory(self.base)));text.config(state='disabled')
    def show_readiness(self):
        from .readiness import readiness_text
        messagebox.showinfo('연결 준비 상태',readiness_text(os.environ),parent=self.root)
    def show_history(self):
        if self.busy:return
        from .presentation import history_text
        store=Store(str(self.base/('demo.sqlite3' if self.demo.get() else 'studio.sqlite3')))
        try:
            rows=list(store.db.execute('SELECT * FROM task_runs ORDER BY id DESC LIMIT 50'))
            pending=[]
            for row in store.db.execute('SELECT id,post_id,status FROM apply_history WHERE status IN ("SENDING","NEEDS_RECONCILE","ROLLBACK_SENDING","ROLLBACK_NEEDS_RECONCILE") ORDER BY id DESC LIMIT 50'):
                pending.append(f"수정 기록 번호 {row['id']} · 글 {row['post_id']} · {row['status']}")
            if store.db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='publish_history'").fetchone():
                for row in store.db.execute('SELECT job_id,status FROM publish_history WHERE status!="VERIFIED" ORDER BY id DESC LIMIT 50'):
                    pending.append(f"생성 작업 번호 {row['job_id']} · 저장 결과 재확인 필요 · {row['status']}")
        finally:store.close()
        dialog=tk.Toplevel(self.root);dialog.title('최근 작업 기록');dialog.geometry('850x550')
        text=ScrolledText(dialog,wrap='word');text.pack(fill='both',expand=True,padx=10,pady=10)
        text.insert('end',('결과 확인이 필요한 기록\n'+'\n'.join(pending)+'\n\n' if pending else '')+history_text(rows));text.config(state='disabled')
    def show_settings(self):
        if self.busy:return
        dialog=tk.Toplevel(self.root);dialog.title('R3.0 연결 설정');dialog.transient(self.root);dialog.grab_set()
        entries={}
        fields=[('R3_BLOG_ID','Blogger 블로그 ID'),('R3_BRIDGE_URL','Bridge 웹 앱 주소'),('R3_BRIDGE_SECRET','Bridge 인증값'),('R3_GEMINI_KEY','Gemini API 키'),('R3_GEMINI_MODEL','Gemini 모델명'),('R3_IMAGE_MODEL','이미지 생성 모델명'),('R3_GSC_PROPERTY','Search Console 속성 주소 (선택)'),('R3_GSC_TOKEN','Search Console 접근 토큰 (선택)')]
        from .settings import SECRET_FIELDS
        for row,(key,label) in enumerate(fields):
            ttk.Label(dialog,text=label).grid(row=row,column=0,sticky='w',padx=10,pady=6)
            entry=ttk.Entry(dialog,width=60,show='*' if key in SECRET_FIELDS else '')
            entry.insert(0,os.environ.get(key,''));entry.grid(row=row,column=1,padx=10,pady=6);entries[key]=entry
        mode=tk.StringVar(value='데모 조회' if self.demo.get() else '실제 Blogger 조회')
        ttk.Label(dialog,text='다음 실행 시 첫 조회').grid(row=len(fields),column=0,padx=10,pady=6)
        ttk.Combobox(dialog,textvariable=mode,values=('데모 조회','실제 Blogger 조회'),state='readonly',width=25).grid(row=len(fields),column=1,sticky='w',padx=10)
        def use(save):
            values={key:entry.get().strip() for key,entry in entries.items()}
            values['R3_START_MODE']='DEMO' if mode.get()=='데모 조회' else 'LIVE'
            try:
                if save:self.settings.save(values)
                self.settings.activate(values);self.demo.set(values['R3_START_MODE']=='DEMO');dialog.destroy()
                self.set_status(text='연결 설정 반영 완료. 실제 연결 조회는 아직 실행하지 않았습니다.')
            except Exception as exc:messagebox.showerror('설정',str(exc),parent=dialog)
        ttk.Button(dialog,text='이번 실행에서만 사용',command=lambda:use(False)).grid(row=len(fields)+1,column=0,pady=12)
        ttk.Button(dialog,text='암호화 저장 후 사용',command=lambda:use(True)).grid(row=len(fields)+1,column=1,pady=12)
    def start_google(self):
        if self.busy: return
        if self.demo.get():
            messagebox.showinfo('R3.0','실제 Blogger LIVE 글을 동기화한 뒤 사용하세요.');return
        self.new_task();self.busy=True;self.button.config(state='disabled')
        threading.Thread(target=self.google_worker,daemon=True).start()
    def google_worker(self):
        store=None;task=None
        from .tasks import TaskLog,finish_error,Cancelled
        try:
            from .google import Monitor,SearchConsole
            store=Store(str(self.base/'studio.sqlite3'));task=TaskLog(store,'Google 상태 감시')
            from .readiness import require_settings
            require_settings(os.environ,'google')
            self.cancel_token.checkpoint()
            adapter=BridgeAdapter.from_environment()
            self.sync_posts(store,adapter,adapter.blog_id)
            token=os.environ.get('R3_GSC_TOKEN','');prop=os.environ.get('R3_GSC_PROPERTY','')
            console=SearchConsole(token,prop) if token and prop else None
            monitor=Monitor(store,console=console);results=[]
            rows=list(store.db.execute('SELECT post_id,url,title,content_hash FROM posts WHERE blog_id=? AND status="LIVE" AND present=1',(adapter.blog_id,)))
            for index,row in enumerate(rows):
                self.cancel_token.checkpoint()
                self.events.put(('progress',f'Google 상태 확인 {index+1}/{len(rows)}'))
                if not row['url']:continue
                result,reused=monitor.check(adapter.blog_id,row['post_id'],row['url'],post_fingerprint=row['content_hash'])
                result.update(title=row['title'],url=row['url'],reused=reused);results.append(result)
            from .presentation import google_sort_key
            results.sort(key=google_sort_key)
            task.finish('COMPLETED')
            self.events.put(('google_done',results))
        except Exception as exc:
            finish_error(task,exc);self.events.put(('error',str(exc)))
        finally:
            if store:store.close()
    def start_job_action(self,action):
        if self.busy:return
        if self.demo.get() and action not in ('jobs','load_job'):
            messagebox.showinfo('R3.0','실제 연결과 저장된 생성 작업이 필요합니다.');return
        if action=='jobs':value=None
        else:
            try:value=int(self.job_id.get())
            except ValueError:
                messagebox.showinfo('R3.0','작업 번호를 입력하세요.');return
        if action=='schedule':
            when=simpledialog.askstring('예약 시간','예약 시각을 입력하세요. 예: 2026-10-10T09:00:00+09:00',parent=self.root)
            if not when:return
            value=(value,when)
        self.start_ai(action,value)
    def start_image_check(self):
        if self.busy: return
        if self.demo.get():
            messagebox.showinfo('R3.0','실제 AI 연결과 생성 작업이 필요합니다.');return
        try: job=int(self.job_id.get())
        except ValueError:
            messagebox.showinfo('R3.0','생성 결과의 작업 번호를 입력하세요.');return
        paths=list(filedialog.askopenfilenames(title='이미지 후보 2장 선택',filetypes=[('이미지','*.png *.jpg *.jpeg *.webp')]))
        if not paths:return
        if len(paths)!=2:
            messagebox.showinfo('R3.0','이미지 2장을 선택하세요.');return
        self.start_ai('images',(job,paths))
    def start_generation(self):
        if self.busy: return
        if self.demo.get():
            messagebox.showinfo('R3.0','실제 글 생성은 데모 모드에서 실행하지 않습니다. Blogger와 AI 연결 검증 후 사용합니다.'); return
        topics=[line.strip() for line in self.topics.get('1.0','end').splitlines() if line.strip()]
        if not 1<=len(topics)<=3:
            messagebox.showinfo('R3.0','주제를 1~3개 입력하세요.'); return
        self.start_ai('generate',topics)
    def start_deep(self):
        if self.busy: return
        selected=self.table.selection()
        if not selected or self.demo.get():
            messagebox.showinfo('R3.0','실제 Blogger 글을 조회한 뒤 검사할 글을 선택하세요.'); return
        self.start_ai('deep',selected[0])
    def start_ai(self,action,value):
        self.new_task();self.busy=True; self.button.config(state='disabled'); self.generate_button.config(state='disabled')
        self.set_status(text='작업 준비 중…')
        threading.Thread(target=self.ai_worker,args=(action,value),daemon=True).start()
    def ai_worker(self,action,value):
        store=None;task=None;adapter=None;current_stage=['연결 준비']
        from .tasks import TaskLog,finish_error,Cancelled
        try:
            from .ai import Gemini,AIError as GeminiError
            from .evidence import collect_cached,EvidenceHold
            from .generation import Generation
            store=Store(str(self.base/'studio.sqlite3'));task=TaskLog(store,{'generate':'새 글 생성','images':'이미지 후보 검사','repair':'기존 글 수정안 생성','apply_repair':'수정안 적용','rollback':'백업 복원','jobs':'보류 목록 조회','load_job':'저장 작업 조회','resume':'이어서 작성','finalize':'최종 검사','generate_images':'이미지 자동 생성','upload_images':'이미지 업로드','draft':'초안 저장','publish':'공개 발행','schedule':'예약 저장','deep':'심층 검사','reconcile':'이전 저장 결과 재확인','reconcile_apply':'수정 결과 확인','reconcile_images':'이미지 업로드 결과 확인','execute_plan':'검토한 저장 계획 실행'}.get(action,'작업'))
            if action in ('jobs','load_job'):
                from .local_jobs import read_jobs
                self.cancel_token.checkpoint()
                result=read_jobs(store,value if action=='load_job' else None)
                task.finish('COMPLETED');self.events.put(('ai_done',result));return
            from .readiness import require_settings,AI_ACTIONS
            require_settings(os.environ,action)
            adapter=BridgeAdapter.from_environment()
            ai=None
            if action in AI_ACTIONS:
                ai=Gemini.from_environment()
                transport=ai.transport
                def guarded_ai(request):
                    self.cancel_token.checkpoint()
                    self.events.put(('progress',current_stage[0]+' · AI 응답 대기 중 (요청 대기 설정 120초)'))
                    try:result=transport(request)
                    except GeminiError as exc:
                        if exc.diagnostic:
                            exc.diagnostic['stage']=current_stage[0]
                            exc.args=(str(exc)+'\n중단 단계: '+current_stage[0],)
                        raise
                    self.cancel_token.checkpoint();return result
                ai.transport=guarded_ai
            def progress(stage,index,total):
                current_stage[0]=stage
                self.cancel_token.checkpoint();self.events.put(('progress',f'{stage} {index}/{total}'))
            # Refresh Blogger before sending local content to any generation/check request.
            self.events.put(('progress','최신 Blogger 상태 동기화 중…'))
            self.cancel_token.checkpoint()
            self.sync_posts(store,adapter,adapter.blog_id,selected_post=value if action=='deep' else None);self.cancel_token.checkpoint(); run_checks(store,adapter.blog_id,force_recheck=True)
            if action in ('repair','apply_repair','rollback','reconcile_apply'):
                from .recovery import Recovery,rollback_verified
                from .bridge import WriteBridgeAdapter
                writer=WriteBridgeAdapter.from_environment()
                if action=='repair':
                    result=Recovery(store,ai,writer,progress).propose(value,self.base/'image_cache')
                    task.finish('CANCELLED' if self.cancel_token.event.is_set() else 'COMPLETED')
                    self.events.put(('repair_ready',result));return
                elif action=='reconcile_apply':
                    from .apply import Apply
                    row=store.db.execute('SELECT status FROM apply_history WHERE id=? AND blog_id=?',(value,writer.blog_id)).fetchone()
                    if row and row['status'].startswith('ROLLBACK_'):
                        from .recovery import reconcile_rollback
                        result=reconcile_rollback(store,writer,value)
                    else:result=Apply(store,writer).reconcile(value)
                elif action=='apply_repair':result=Recovery(store,ai,writer,progress).apply_proposal(value)
                else:result=rollback_verified(store,writer,value)
            elif action in ('jobs','load_job','resume','finalize','generate_images','upload_images','draft','publish','schedule','reconcile','reconcile_images','execute_plan'):
                generation=Generation(store,ai,adapter.blog_id,progress)
                if action=='jobs':result=generation.pending_jobs()
                elif action=='load_job':result=generation.load_job(value)
                elif action=='resume':result=generation.resume(value)
                elif action=='generate_images':
                    from .imagegen import Generator,generate_candidates
                    result=generate_candidates(generation,Generator.from_environment(),value,self.base/'generated_images')
                elif action=='upload_images':
                    from .bridge import WriteBridgeAdapter
                    from .layout import upload_checked
                    import uuid
                    writer=WriteBridgeAdapter.from_environment();payload=generation.load_job(value)['payload']
                    images=payload.get('image_candidates',[])
                    if len(images)!=2 or any(x.get('result')!='PASS' for x in images):raise ValueError('QA PASS 이미지 2장 필요')
                    receipts=payload.get('upload_receipts',[])
                    for index,image in enumerate(images):
                        if index<len(receipts):continue
                        requests=payload.setdefault('upload_requests',[])
                        if index<len(requests):raise ValueError('이 이미지의 이전 업로드 결과 확인 필요: 중복 업로드 중지')
                        request_id=str(uuid.uuid4());requests.append({'id':request_id,'status':'SENDING','byte_hash':image['info']['byte_hash']})
                        generation.save(value,'이미지 업로드 요청','HOLD',payload)
                        receipt=upload_checked(writer,image,request_id);receipts.append(receipt)
                        requests[index]['status']='VERIFIED'
                        payload['upload_receipts']=receipts;generation.save(value,'이미지 업로드','HOLD',payload)
                    result=generation.compose_uploaded(value,receipts)
                elif action=='reconcile_images':
                    from .bridge import WriteBridgeAdapter
                    from .layout import reconcile_uploads
                    result=reconcile_uploads(generation,WriteBridgeAdapter.from_environment(),value)
                elif action=='reconcile':
                    from .bridge import WriteBridgeAdapter
                    from .publish import Publisher
                    result=Publisher(generation,WriteBridgeAdapter.from_environment()).reconcile(value)
                elif action=='execute_plan':
                    from .bridge import WriteBridgeAdapter
                    from .publish import Publisher
                    result=Publisher(generation,WriteBridgeAdapter.from_environment()).execute(value)
                elif action in ('draft','publish','schedule'):
                    from .bridge import WriteBridgeAdapter
                    from .publish import Publisher,prepare
                    mode={'draft':'DRAFT','publish':'LIVE','schedule':'SCHEDULED'}[action]
                    job,when=value if action=='schedule' else (value,None)
                    plan=prepare(generation,job,mode,when)
                    preview=generation.load_job(job)['payload']
                    task.finish('COMPLETED');self.events.put(('publication_ready',plan,preview.get('search_description','')));return
                else:
                    row=store.db.execute('SELECT url FROM posts WHERE blog_id=? AND status="LIVE" AND present=1 AND url!="" LIMIT 1',(adapter.blog_id,)).fetchone()
                    if not row:raise ValueError('사이트 주소를 확인할 LIVE 글이 필요합니다.')
                    from urllib.parse import urlparse
                    parsed=urlparse(row['url']);base_url=parsed.scheme+'://'+parsed.netloc+'/'
                    result=generation.finalize_job(value,base_url,self.base/'image_cache')
            elif action=='images':
                result=Generation(store,ai,adapter.blog_id,progress).check_image_candidates(value[0],value[1])
            elif action=='generate':
                result=Generation(store,ai,adapter.blog_id,progress).generate_many(value)
            else:
                row=store.db.execute('SELECT title,content,content_hash FROM posts WHERE blog_id=? AND post_id=? AND present=1',(adapter.blog_id,value)).fetchone()
                if not row: raise ValueError('최신 Blogger 목록에 없는 글입니다.')
                try:
                    pack=collect_cached(store,ai,row['title'],row['title'],adapter.blog_id+':'+value+':'+row['content_hash'],progress,article=row['content'])
                except (GeminiError,EvidenceHold) as exc:
                    from .existing import partial_link_review,record_incomplete
                    partial=None
                    try:partial=partial_link_review(store,adapter,value,progress)
                    except Cancelled:raise
                    except Exception:pass # Preserve the original classified research error.
                    incomplete=record_incomplete(store,adapter.blog_id,value,exc,partial)
                    if incomplete:self.events.put(('inspection_incomplete',incomplete))
                    exc.partial_recorded=True
                    raise
                from .existing import inspect_existing
                result=inspect_existing(store,adapter,ai,value,pack,self.base/'image_cache',progress)
            task.finish('COMPLETED')
            self.events.put(('ai_done',result))
        except Exception as exc:
            if action=='deep' and store and adapter and not getattr(exc,'partial_recorded',False):
                from .existing import record_incomplete,partial_link_review
                from .bridge import BridgeError
                partial=None
                if not isinstance(exc,(BridgeError,Cancelled)):
                    try:partial=partial_link_review(store,adapter,value,progress)
                    except Exception:pass
                incomplete=record_incomplete(store,adapter.blog_id,value,exc,partial)
                if incomplete:self.events.put(('inspection_incomplete',incomplete))
            finish_error(task,exc);self.events.put(('error',str(exc)))
        finally:
            if store: store.close()
    def start(self):
        if self.busy: return
        self.new_task();self.busy=True; self.button.config(state='disabled'); demo=self.demo.get()
        self.set_status(text='데모 조회 중…' if demo else 'Blogger LIVE / SCHEDULED / DRAFT 조회 중…')
        threading.Thread(target=self.worker,args=(demo,),daemon=True).start()
    def worker(self,demo):
        store=None;task=None
        from .tasks import TaskLog,finish_error,Cancelled
        try:
            store=Store(str(self.base/('demo.sqlite3' if demo else 'studio.sqlite3')));task=TaskLog(store,'LIVE 동기화 + 빠른 검사')
            if not demo:
                from .readiness import require_settings
                require_settings(os.environ,'sync')
            adapter=DemoAdapter() if demo else BridgeAdapter.from_environment()
            blog_id='DEMO' if demo else adapter.blog_id
            self.cancel_token.checkpoint()
            sync=self.sync_posts(store,adapter,blog_id);self.cancel_token.checkpoint(); checks=run_checks(store,blog_id,force_recheck=True)
            rows=[]
            for row in store.db.execute('SELECT * FROM posts WHERE blog_id=? AND present=1 ORDER BY CASE WHEN grade LIKE "EMPTY%" OR grade="INCOMPLETE_DRAFT" THEN 0 WHEN status="SCHEDULED" THEN 1 ELSE 2 END,post_id',(blog_id,)):
                data=dict(row); latest=store.db.execute('SELECT details FROM recovery_checks WHERE blog_id=? AND post_id=? ORDER BY id DESC LIMIT 1',(blog_id,data['post_id'])).fetchone()
                data['details']=json.loads(latest[0]) if latest else {}
                if data['details'].get('verified') and data['details'].get('grade')!=data['grade']:
                    data['details']['verified']=False
                    data['details'].setdefault('issues',[]).append('이전 전체 검사 이후 목록 변경 또는 유효기간 만료: 재검사 필요')
                duplicate=store.db.execute('SELECT details FROM duplicate_checks WHERE blog_id=? AND post_id=?',(blog_id,data['post_id'])).fetchone()
                matches=json.loads(duplicate[0]) if duplicate else []
                data['details'].setdefault('metrics',{})['similar_posts']=matches
                if matches: data['details'].setdefault('issues',[]).append('다른 글과 높은 기본 유사도')
                rows.append(data)
            task.finish('COMPLETED')
            self.events.put(('done',sync,checks,rows,demo))
        except Exception as exc:
            finish_error(task,exc)
            # No credential, endpoint or raw remote payload is written to logs.
            self.events.put(('error',str(exc)))
        finally:
            if store: store.close()
    def poll(self):
        try:
            while True:
                event=self.events.get_nowait()
                if event[0]=='inspection_incomplete':
                    result=event[1];pid=result['post_id']
                    if pid in self.results:
                        self.results[pid]['grade']=result['grade'];self.results[pid]['details']=result;self.table.set(pid,'grade',result['grade']);self.detail()
                    continue
                if event[0]=='progress':
                    self.set_status(text=event[1]); self.generation_notes.insert('end',event[1]+'\n'); self.generation_notes.see('end'); continue
                if event[0]=='google_done':
                    self.busy=False;self.button.config(state='normal');self.google_notes.delete('1.0','end')
                    for r in event[1]:
                        from .presentation import google_text
                        self.google_notes.insert('end',google_text(r))
                    self.set_status(text='Google 상태 기록 완료 · 색인 요청 제출 없음');continue
                if event[0]=='publication_ready':
                    self.busy=False;self.button.config(state='normal');self.generate_button.config(state='normal');self.show_publication(event[1],event[2]);continue
                if event[0]=='repair_ready':
                    self.busy=False;self.button.config(state='normal');self.generate_button.config(state='normal');self.show_repair(event[1]);continue
                if event[0]=='ai_done':
                    self.busy=False; self.button.config(state='normal'); self.generate_button.config(state='normal')
                    if isinstance(event[1],dict) and event[1].get('audit_id') and event[1].get('status')=='VERIFIED':self.last_apply_id=event[1]['audit_id']
                    if isinstance(event[1],dict) and event[1].get('grade') and event[1].get('post_id') in self.results:
                        pid=event[1]['post_id'];self.results[pid]['grade']=event[1]['grade'];self.results[pid]['details']=event[1]
                        self.table.set(pid,'grade',event[1]['grade']);self.detail()
                    from .presentation import result_text
                    if isinstance(event[1],dict) and event[1].get('job_id'):
                        self.job_id.delete(0,'end');self.job_id.insert(0,str(event[1]['job_id']))
                    self.generation_notes.insert('end',result_text(event[1])+'\n\n');self.generation_notes.see('end')
                    local=event[1].get('local_only') if isinstance(event[1],dict) else bool(event[1]) and all(x.get('local_only') for x in event[1])
                    self.set_status(text='저장 기록 조회 완료 · 최신 Blogger 조회 없음' if local else '작업 종료 · 결과 기록 완료'); continue
                self.busy=False; self.button.config(state='normal'); self.generate_button.config(state='normal')
                if event[0]=='error': self.set_status(text='작업 중지 · 기록에서 결과를 확인하세요.'); messagebox.showerror('R3.0',event[1]); continue
                _,sync,checks,rows,demo=event
                self.table.delete(*self.table.get_children()); self.results={r['post_id']:r for r in rows}
                for r in rows: self.table.insert('', 'end',iid=r['post_id'],values=(r['status'],r['grade'],r['title'] or '(제목 없음)',r['updated']))
                from .presentation import inspection_summary
                self.set_status(text=inspection_summary(sync,checks,rows,demo))
        except queue.Empty: pass
        self.root.after(100,self.poll)
    def detail(self,event=None):
        selected=self.table.selection()
        if not selected: return
        r=self.results[selected[0]]; d=r['details']; self.notes.delete('1.0','end')
        from .presentation import inspection_text
        self.notes.insert('end',inspection_text(r))
def main():
    from .startup import launch
    return launch()
if __name__=='__main__': main()
