"""Desktop development UI. Tk is accessed only from the main thread."""
import json
import os
from pathlib import Path
import queue
import threading
import time
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
        self.root=root; root.title('R3.0 Blogger 통합 스튜디오 · Dev89 시험판'); root.geometry('1080x720')
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
        ttk.Label(controls,text='이전 기록 재사용 · 변경된 글만 조회·검사').pack(side='left',padx=15)
        ttk.Button(controls,text='수정안 만들기',command=self.start_repair).pack(side='left')
        ttk.Button(controls,text='수정·복원 결과 확인',command=self.start_apply_reconcile).pack(side='left',padx=5)
        ttk.Button(controls,text='수정 백업 복원',command=self.start_rollback).pack(side='left',padx=5)
        ttk.Button(controls,text='선택 글 심층 검사',command=self.start_deep).pack(side='right')
        whole_controls=ttk.Frame(self.inspect);whole_controls.pack(fill='x',pady=(6,0))
        ttk.Button(whole_controls,text='전체 강제 재검사',command=lambda:self.start(force=True)).pack(side='right',padx=5)
        ttk.Button(whole_controls,text='본문·이미지 전체 새로 만들기',command=self.start_replacement).pack(side='left')
        ttk.Button(whole_controls,text='전체 교체 작업 불러오기',command=self.show_replacement_jobs).pack(side='left',padx=8)
        ttk.Label(whole_controls,text='선택한 기존 글의 번호·주소 유지 · 검토 후 적용').pack(side='left',padx=10)
        self.status=ttk.Label(self.inspect,textvariable=self.status_text,wraplength=1000); self.status.pack(anchor='w',pady=10)
        self.inspect_panes=ttk.Panedwindow(self.inspect,orient='vertical');self.inspect_panes.pack(fill='both',expand=True)
        table_frame=ttk.Frame(self.inspect_panes);self.inspect_panes.add(table_frame,weight=3)
        self.table=ttk.Treeview(table_frame,columns=('state','grade','title','updated'),show='headings')
        for name,label,width in [('state','상태',110),('grade','검사 결과',220),('title','제목',430),('updated','Blogger 수정 시각',220)]:
            self.table.heading(name,text=label); self.table.column(name,width=width)
        scroll=ttk.Scrollbar(table_frame,orient='vertical',command=self.table.yview);scroll.pack(side='right',fill='y')
        self.table.config(yscrollcommand=scroll.set)
        self.table.pack(side='left',fill='both',expand=True); self.table.bind('<<TreeviewSelect>>',self.detail)
        detail_frame=ttk.Frame(self.inspect_panes);self.inspect_panes.add(detail_frame,weight=2)
        self.notes=ScrolledText(detail_frame,height=12,wrap='word'); self.notes.pack(fill='both',expand=True,pady=8)
        ttk.Label(self.inspect,text='단계 진행 표시 · 단계별 처리량과 AI 대기는 아래 기록에서 확인합니다.').pack(anchor='w',before=self.inspect_panes)
        progress_frame=ttk.Frame(self.inspect);progress_frame.pack(fill='x',pady=4,before=self.inspect_panes)
        self.progress_bar=ttk.Progressbar(progress_frame,mode='determinate',maximum=9,value=0);self.progress_bar.pack(side='left',fill='x',expand=True)
        self.elapsed_text=tk.StringVar(value='대기 중');ttk.Label(progress_frame,textvariable=self.elapsed_text).pack(side='right',padx=10)
        self.inspection_log=ScrolledText(self.inspect,height=4,wrap='word');self.inspection_log.pack(fill='x',before=self.inspect_panes)
        self.task_started=None;self.progress_mode=None
        self.results={};self.last_apply_id=None; root.after(100,self.poll)
        from .start_mode import auto_start_enabled
        if auto_start_enabled(os.environ):root.after(300,self.start)
        else:self.set_status('조회 대기 · LIVE 동기화 + Fast 검사를 누르면 시작합니다.')
        root.after(500,self.refresh_elapsed)
    def set_status(self,text):
        self.status_text.set(text)
        if hasattr(self,'progress_bar') and not self.busy:
            self.progress_mode=None
            if self.task_started is not None:self.task_elapsed=int(time.monotonic()-self.task_started)
    def refresh_elapsed(self):
        if self.busy and self.task_started is not None:
            seconds=int(time.monotonic()-self.task_started)
            self.elapsed_text.set(f'경과 {seconds//60}분 {seconds%60}초')
        elif self.task_started is not None:
            seconds=getattr(self,'task_elapsed',0)
            self.elapsed_text.set(f'{getattr(self,"task_outcome",None) or "종료"} · {seconds//60}분 {seconds%60}초')
        self.root.after(500,self.refresh_elapsed)
    def update_progress(self,text):
        from .progress import progress_state
        state=progress_state(text)
        from .progress import StageProgress
        if not hasattr(self,'stage_progress'):self.stage_progress=StageProgress()
        position=self.stage_progress.update(text)
        self.progress_bar.config(mode='determinate',maximum=9,value=position)
        # A waiting line is a live indicator, not a permanent claim of activity.
        if getattr(self,'waiting_line',None):
            self.inspection_log.delete(self.waiting_line,self.waiting_line+' lineend+1c');self.waiting_line=None
        if state['waiting']:self.waiting_line=self.inspection_log.index('end-1c')
        self.inspection_log.insert('end',text+' · '+state['label']+'\n');self.inspection_log.see('end')
    def finish_progress(self,event):
        from .progress import terminal_summary
        summary=terminal_summary(event)
        self.busy=False
        if self.task_started is not None:self.task_elapsed=int(time.monotonic()-self.task_started)
        if getattr(self,'waiting_line',None):
            self.inspection_log.delete(self.waiting_line,self.waiting_line+' lineend+1c');self.waiting_line=None
        self.inspection_log.insert('end',summary+' · 현재 실행 중인 작업 없음\n');self.inspection_log.see('end')
        self.elapsed_text.set(f'{summary.split(" · ")[0]} · {self.task_elapsed//60}분 {self.task_elapsed%60}초')
        self.task_outcome=summary.split(' · ')[0]
    def sync_posts(self,store,adapter,blog_id,selected_post=None,force=False):
        def progress(stage,index,total):
            text=f'{stage} {index}/{total}' if total else f'{stage} · {index}개 확인'
            self.events.put(('progress',text))
        from .cache_policy import force_whole_review
        return Sync(store,adapter,blog_id,progress,self.cancel_token.checkpoint,force_refresh=selected_post is None and force_whole_review(force=force),refresh_ids=() if selected_post is None else (selected_post,)).run()
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
        self.task_started=time.monotonic();self.task_elapsed=0
        from .progress import StageProgress
        self.stage_progress=StageProgress()
        self.progress_bar.stop();self.progress_bar.config(mode='determinate',maximum=9,value=0)
        self.inspection_log.delete('1.0','end')
        self.waiting_line=None;self.task_outcome=None
    def start_repair(self):
        if self.busy:return
        selected=self.table.selection()
        if not selected or self.demo.get():
            messagebox.showinfo('R3.0','실제 글을 조회하고 수정할 글을 선택하세요.');return
        self.start_ai('repair',selected[0])
    def show_replacement_jobs(self):
        if self.busy:return
        blog_id=os.environ.get('R3_BLOG_ID','')
        if not blog_id:messagebox.showinfo('R3.0','연결 설정에 블로그 ID를 입력하세요.');return
        store=Store(str(self.base/'studio.sqlite3'))
        try:
            from .replacement import saved_replacements
            saved=saved_replacements(store,blog_id)
        finally:store.close()
        if not saved:messagebox.showinfo('R3.0','보관된 전체 교체 작업이 없습니다.');return
        window=tk.Toplevel(self.root);window.title('보관된 전체 교체 작업');window.geometry('900x420')
        table=ttk.Treeview(window,columns=('post','job','status','title'),show='headings');table.pack(fill='both',expand=True,padx=10,pady=10)
        for key,label in [('post','기존 글 번호'),('job','생성 작업 번호'),('status','상태'),('title','새 제목 / 주제')]:table.heading(key,text=label)
        for item in saved:table.insert('', 'end',iid=str(item['proposal_id']),values=(item['before']['id'],item.get('replacement_job_id',''),item['status'],item.get('proposed_title',item.get('replacement_topic',''))))
        def load():
            selection=table.selection()
            if selection:self.show_repair(next(item for item in saved if str(item['proposal_id'])==selection[0]));window.destroy()
        ttk.Button(window,text='선택 작업 불러오기',command=load).pack(pady=8)
    def start_replacement(self):
        if self.busy:return
        selected=self.table.selection()
        if not selected or self.demo.get():
            messagebox.showinfo('R3.0','실제 블로그 글을 조회하고 전체 교체할 글을 선택하세요.');return
        post_id=selected[0]
        topic=simpledialog.askstring('본문·이미지 전체 새로 만들기','새로 작성할 제목을 입력하세요. 입력한 제목을 그대로 사용합니다.\n기존 글 번호·주소를 유지하며, 생성 후 검토와 최종 검증을 거칩니다.',initialvalue=self.results.get(post_id,{}).get('title',''),parent=self.root)
        if topic and topic.strip():self.start_ai('replace_post',{'post_id':post_id,'topic':topic.strip()})
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
    def show_replacement_hold(self,result):
        from .replacement import replacement_view
        view=replacement_view(result);pid=result['proposal_id']
        windows=getattr(self,'replacement_hold_windows',{});self.replacement_hold_windows=windows
        dialog=windows.get(pid)
        if dialog is None or not dialog.winfo_exists():
            dialog=tk.Toplevel(self.root);dialog.geometry('800x480');windows[pid]=dialog
        for child in dialog.winfo_children():child.destroy()
        dialog.title('전체 교체 생성 보류 · 본문 미작성')
        ttk.Label(dialog,text='새 본문을 아직 작성하지 못했습니다.',font=('',14,'bold')).pack(anchor='w',padx=15,pady=12)
        text=ScrolledText(dialog,wrap='word',height=12);text.pack(fill='both',expand=True,padx=15,pady=8)
        text.insert('end','기존 글 번호: '+str(result['before'].get('id',''))+'\n입력한 새 제목: '+view['topic']+'\n생성된 제목: '+view['title']+'\n중단 단계: '+view['stage']+'\n보류 원인: '+view['reason']+'\n\nBlogger의 기존 글과 이미지는 변경되지 않았습니다.\n')
        from .presentation import diagnostic_lines
        recovery=result.get('generation_evidence_recovery',{})
        if recovery:
            state={'STARTED':'진행 중','VERIFIED':'원문 검증 완료','FAILED':'근거 미확보 또는 오류로 종료'}.get(recovery.get('state'),'기록 확인 필요')
            text.insert('end','\n확인된 원문으로 근거 재구성: '+state+' · 1회 한도\n')
        text.insert('end','\n'.join(diagnostic_lines(result.get('error_diagnostic',{}))))
        if view['can_resume']:text.insert('end','\n같은 작업 이어서 진행은 저장된 작업 번호와 입력 제목을 유지합니다.')
        else:text.insert('end','\n생성 작업 번호가 없습니다. 같은 제목의 저장 작업 확인 또는 제목 변경이 필요합니다.')
        text.config(state='disabled')
        controls=ttk.Frame(dialog);controls.pack(fill='x',padx=15,pady=12)
        if view['can_resume']:
            def resume():
                if self.busy:return
                dialog.withdraw();self.start_ai('replace_resume',{'proposal_id':pid})
            ttk.Button(controls,text='같은 작업 이어서 진행',command=resume).pack(side='left')
        def change_title():
            if self.busy:return
            title=simpledialog.askstring('전체 교체 제목 확인','새로 작성할 제목을 입력하세요. 같은 제목이면 저장된 교체 작업을 이어갑니다.',initialvalue=view['topic'],parent=dialog)
            if title and title.strip():
                dialog.withdraw();self.start_ai('replace_all',{'proposal_id':pid,'topic':title.strip()})
        ttk.Button(controls,text='제목 확인·변경하여 진행',command=change_title).pack(side='left',padx=8)
        ttk.Button(controls,text='닫기',command=dialog.destroy).pack(side='right')
        dialog.deiconify();return dialog
    def show_repair(self,result):
        if result.get('mode')=='REPLACEMENT':
            from .replacement import replacement_view
            if not replacement_view(result)['has_body']:return self.show_replacement_hold(result)
            previous=getattr(self,'replacement_hold_windows',{}).pop(result['proposal_id'],None)
            if previous is not None and previous.winfo_exists():previous.destroy()
        pid=result['proposal_id']
        windows=getattr(self,'repair_windows',{});self.repair_windows=windows
        dialog=windows.get(pid)
        if dialog is None or not dialog.winfo_exists():
            dialog=tk.Toplevel(self.root);dialog.geometry('1050x700');windows[pid]=dialog
        editor=getattr(dialog,'image_editor',None)
        editor_open=bool(editor is not None and editor.winfo_exists() and editor.state()!='withdrawn')
        selected_slot=getattr(dialog,'selected_image_slot',1)
        for child in dialog.winfo_children():child.destroy()
        dialog.preview_widgets=[];dialog.preview_image_refs=[]
        dialog.title('수정안 비교 · '+result['status'])
        def replace_all():
            if self.busy:return
            topic=simpledialog.askstring('본문·이미지 전체 새로 만들기','새로 작성할 제목을 입력하세요. 입력한 제목을 그대로 사용합니다.\n새 본문과 이미지 2장을 만들고, 기존 글 번호·주소를 유지합니다.\n생성만으로 Blogger 글이 변경되지는 않습니다.',initialvalue=result.get('replacement_topic',result['before'].get('title','')),parent=dialog)
            if topic and topic.strip():self.start_ai('replace_all',{'proposal_id':pid,'topic':topic.strip()})
        replacement_controls=ttk.Frame(dialog);replacement_controls.pack(fill='x',padx=10,pady=5)
        ttk.Button(replacement_controls,text='본문·이미지 전체 새로 만들기',command=replace_all).pack(side='left')
        if result.get('replacement_job_id'):
            ttk.Button(replacement_controls,text='전체 교체 작업 이어서 진행',command=lambda:self.start_ai('replace_resume',{'proposal_id':pid}) if not self.busy else None).pack(side='left',padx=8)
        from .final_text_repair import repairable_diagnostic
        if result.get('mode')=='REPLACEMENT' and repairable_diagnostic(result.get('error_diagnostic',{})):
            from .source_domains import claims_not_evaluated
            from .final_text_repair import evidence_problem
            saved_detail=result.get('error_diagnostic',{})
            detail=evidence_problem(saved_detail)
            repair_label=('근거 지적 문단 나누어 보완 · 이미지 유지' if detail!=saved_detail else
                          '근거 장부·미확보 문장 보완' if detail.get('reason')=='EVIDENCE_INCOMPLETE' else
                          '출처 단계 재검증 · 본문 보존' if claims_not_evaluated(detail) else '근거 미확보 문장 보완')
            ttk.Button(replacement_controls,text=repair_label,command=lambda:self.start_ai('repair_evidence',{'proposal_id':pid}) if not self.busy else None).pack(side='left',padx=8)
        ttk.Button(replacement_controls,text='수정안 최종 검증',state='disabled' if result.get('mode')=='REPLACEMENT' and not result.get('replacement_preview_ready') else 'normal',command=lambda:self.start_ai('repair_validate',{'proposal_id':pid,'slot':1}) if not self.busy else None).pack(side='right')
        title=result.get('proposed_title') or result.get('plan',{}).get('proposal',{}).get('title') or ('아직 생성되지 않음' if result.get('mode')=='REPLACEMENT' else result['before'].get('title',''))
        requested='\n입력한 새 제목: '+result.get('replacement_topic','') if result.get('mode')=='REPLACEMENT' else ''
        ttk.Label(dialog,text='기존 제목: '+result['before'].get('title','')+requested+'\n수정안 제목: '+title+'\n기존 상태: '+result['before'].get('status','')+' · 예약/발행 시각: '+str(result['before'].get('published','미확인')),wraplength=1000).pack(fill='x',padx=10)
        from .gates import Document
        tabs=ttk.Notebook(dialog);tabs.pack(fill='both',expand=True,padx=10,pady=10)
        comparison=ttk.Frame(tabs);tabs.add(comparison,text='글·이미지 비교')
        if result.get('mode')=='REPLACEMENT':
            from .text_flow import report
            diagnosis_tab=ttk.Frame(tabs);tabs.add(diagnosis_tab,text='본문 검사·보완 기록')
            detail=ScrolledText(diagnosis_tab,wrap='word');detail.pack(fill='both',expand=True)
            detail.insert('end',report(result));detail.config(state='disabled')

        if editor is None or not editor.winfo_exists():
            editor=tk.Toplevel(self.root);editor.geometry('950x760');editor.withdraw();dialog.image_editor=editor
        for child in editor.winfo_children():child.destroy()
        editor.preview_widgets=[];editor.preview_image_refs=[]
        editor.title('이미지 수정 · 글 비교창은 계속 열려 있습니다')
        editor.protocol('WM_DELETE_WINDOW',editor.withdraw)
        dialog.protocol('WM_DELETE_WINDOW',lambda:(editor.destroy(),dialog.destroy()))
        image_tab=ttk.Frame(editor,padding=10);image_tab.pack(fill='both',expand=True)
        def open_editor():editor.deiconify();editor.lift()
        ttk.Button(dialog,text='이미지 수정 · 별도 창 열기',command=open_editor).pack(anchor='w',padx=10)
        if editor_open:open_editor()
        panes=ttk.Panedwindow(comparison,orient='horizontal');panes.pack(fill='both',expand=True)
        original=result['before'].get('content','');proposed=result.get('plan',{}).get('proposal',{}).get('content',result.get('proposed_content',''))
        from .preview import show_article_comparison
        show_article_comparison(dialog,panes,original,proposed,result.get('image_review',{}).get('items',[]),self.base/'image_cache',choices=result.get('image_choices',{}) if result['status']!='PASS' else None)
        ttk.Label(dialog,text='수정안 상태: '+('최종 검증 통과' if result['status']=='PASS' else '검증 미완료 · 미반영 제안은 적용 내용과 구분해 표시합니다.'),wraplength=1000).pack(fill='x',padx=10)
        ttk.Label(dialog,text=result.get('reason') or '수정 이유: '+' / '.join(str(x) for x in result.get('changes',[])),wraplength=1000).pack(fill='x',padx=10,pady=8)
        from .gates import Document
        count=len(Document(proposed).images);slot=tk.IntVar(value=min(selected_slot,count) if count else 1)
        controls=ttk.Frame(image_tab);controls.pack(fill='x',pady=6)
        ttk.Label(controls,text='수정할 이미지:').pack(side='left')
        selector=ttk.Combobox(controls,textvariable=slot,values=list(range(1,count+1)),state='readonly',width=5);selector.pack(side='left',padx=8)
        editor.image_slot=slot
        ttk.Label(image_tab,text='후보를 먼저 검사합니다. 본문 관련성·실제 픽셀·ALT·설명이 통과한 후보만 선택할 수 있습니다.',wraplength=900).pack(anchor='w',pady=8)
        def image_action(action):
            if self.busy:return
            value={'proposal_id':result['proposal_id'],'slot':slot.get()}
            if action=='repair_image_import':
                path=filedialog.askopenfilename(parent=editor,title='교체할 이미지 선택',filetypes=[('이미지','*.png *.jpg *.jpeg *.webp')])
                if not path:return
                value['path']=path
            dialog.selected_image_slot=slot.get();self.start_ai(action,value)
        for label,action in [('이미지 수정 · 파일 선택','repair_image_import'),('이미지 재생성','repair_image_generate'),('ALT·그림 설명 재생성','repair_alt'),('이 후보로 교체','repair_image_choose'),('이미지 후보 선택 취소' if result.get('mode')=='REPLACEMENT' else '이미지 취소 · 기존 이미지 유지','repair_image_cancel'),('수정안 최종 검증','repair_validate')]:
            ttk.Button(image_tab,text=label,command=lambda a=action:image_action(a),state='normal' if count else 'disabled').pack(anchor='w',pady=4)
        ttk.Label(image_tab,text='교체 이미지는 최종 검증 때 공개 이미지 저장소에 업로드합니다. Blogger 글은 검토한 수정안 적용 버튼을 누르기 전까지 바뀌지 않습니다.',wraplength=900).pack(anchor='w',pady=8)
        info=ScrolledText(image_tab,wrap='word',height=4);info.pack(fill='both',expand=True,pady=8)
        for index,item in enumerate(Document(proposed).images,1):
            key=str(index);candidate=result.get('image_edit_candidates',{}).get(key,{})
            selected=result.get('image_choices',{}).get(key,{})
            info.insert('end',f'이미지 {index} · '+('후보 선택됨 · 최종 검증 전' if selected and result['status']!='PASS' else '현재 수정안 이미지')+'\n')
            if candidate:
                info.insert('end','새 후보 검사: '+candidate.get('result','HOLD')+'\nALT: '+candidate.get('alt','')+'\n그림 설명: '+candidate.get('caption','')+'\n'+candidate.get('reason','')+'\n')
            info.insert('end','\n')
        info.config(state='disabled')
        # Show only the selected slot's actual pixels beside its newest candidate.
        selected_label=ttk.Label(image_tab);selected_label.pack(anchor='w')
        selected_preview=ttk.Panedwindow(image_tab,orient='horizontal');selected_preview.pack(fill='both',expand=True)
        def show_selected(event=None):
            import html
            index=slot.get();dialog.selected_image_slot=index
            for child in selected_preview.winfo_children():child.destroy()
            if not count:return
            image=Document(proposed).images[index-1];url=image.get('src','')
            candidate=result.get('image_edit_candidates',{}).get(str(index),{})
            choice=result.get('image_choices',{}).get(str(index),{})
            selected_label.config(text=f'선택: 이미지 {index} / {count} · ALT 재생성 대상: '+('선택한 교체 이미지' if choice else '현재 수정안 이미지')+' · 오른쪽은 새 후보이며 교체 전에는 반영되지 않습니다.')
            content='<figure><img src="'+html.escape(url,quote=True)+'" alt="'+html.escape(image.get('alt',''),quote=True)+'"></figure>'
            review=[dict(r,index=1) for r in result.get('image_review',{}).get('items',[]) if r.get('index')==index and r.get('url')==url]
            current_choices={'1':choice} if choice else None
            # Render the current selected pixels as the left side too.
            from .preview import preview_parts
            if choice:
                c=choice['candidate'];review=[{'index':1,'url':url,'preview_file':c['file'],'pixel_hash':c['info']['pixel_hash']}]
                content='<figure><img src="'+html.escape(url,quote=True)+'" alt="'+html.escape(c.get('alt',''),quote=True)+'"><figcaption>'+html.escape(c.get('caption',''))+'</figcaption></figure>'
            preview_choice={'1':{'candidate':candidate,'expected_url':url,'preview_only':True}} if candidate.get('file') and candidate.get('info') else current_choices
            show_article_comparison(editor,selected_preview,content,content,review,self.base/'image_cache',choices=preview_choice,image_number=index,labels=('현재 선택 이미지','새 후보 · 교체 전'))
        selector.bind('<<ComboboxSelected>>',show_selected);show_selected()
        # Preview the newest candidate locally before the user chooses it.
        candidates=result.get('image_edit_candidates',{})
        if candidates:
            candidate_tab=ttk.Frame(tabs);tabs.add(candidate_tab,text='생성·수정 후보 보기')
            candidate_panes=ttk.Panedwindow(candidate_tab,orient='horizontal');candidate_panes.pack(fill='both',expand=True)
            candidate_choices={k:{'candidate':c,'expected_url':Document(proposed).images[int(k)-1].get('src',''),'preview_only':True} for k,c in candidates.items() if c.get('file') and c.get('info') and k.isdigit() and 1<=int(k)<=count}
            show_article_comparison(dialog,candidate_panes,proposed,proposed,result.get('image_review',{}).get('items',[]),self.base/'image_cache',choices=candidate_choices)
        def apply():
            if self.busy:return
            editor.destroy();dialog.destroy();self.start_ai('apply_repair',{'id':result['proposal_id'],'expected':result.get('proposal_hash')})
        ttk.Button(dialog,text='검토한 수정안 적용',command=apply,state='normal' if result['status']=='PASS' else 'disabled').pack(pady=10)
        return dialog
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
        automatic=tk.BooleanVar(value=os.environ.get('R3_AUTO_SYNC')=='1')
        ttk.Checkbutton(dialog,text='프로그램 시작 시 자동 조회',variable=automatic).grid(row=len(fields)+1,column=1,sticky='w',padx=10,pady=6)
        def use(save):
            values={key:entry.get().strip() for key,entry in entries.items()}
            values['R3_AUTO_SYNC']='1' if automatic.get() else '0'
            values['R3_START_MODE']='DEMO' if mode.get()=='데모 조회' else 'LIVE'
            try:
                if save:self.settings.save(values)
                self.settings.activate(values);self.demo.set(values['R3_START_MODE']=='DEMO');dialog.destroy()
                self.set_status(text='연결 설정 반영 완료. 실제 연결 조회는 아직 실행하지 않았습니다.')
            except Exception as exc:messagebox.showerror('설정',str(exc),parent=dialog)
        ttk.Button(dialog,text='이번 실행에서만 사용',command=lambda:use(False)).grid(row=len(fields)+2,column=0,pady=12)
        ttk.Button(dialog,text='암호화 저장 후 사용',command=lambda:use(True)).grid(row=len(fields)+2,column=1,pady=12)
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
            store=Store(str(self.base/'studio.sqlite3'));task=TaskLog(store,{'generate':'새 글 생성','images':'이미지 후보 검사','repair':'기존 글 수정안 생성','apply_repair':'수정안 적용','rollback':'백업 복원','jobs':'보류 목록 조회','load_job':'저장 작업 조회','resume':'이어서 작성','finalize':'최종 검사','generate_images':'이미지 자동 생성','upload_images':'이미지 업로드','draft':'초안 저장','publish':'공개 발행','schedule':'예약 저장','deep':'심층 검사','reconcile':'이전 저장 결과 재확인','reconcile_apply':'수정 결과 확인','reconcile_images':'이미지 업로드 결과 확인','repair_image_import':'수정 이미지 후보 검사','repair_image_generate':'수정 이미지 재생성','repair_alt':'ALT·설명 재생성','repair_image_choose':'이미지 후보 선택','repair_image_cancel':'이미지 후보 취소','repair_validate':'수정안 최종 검증','repair_evidence':'근거 미확보 문장 보완','replace_post':'본문·이미지 전체 새로 만들기','replace_all':'본문·이미지 전체 새로 만들기','replace_resume':'전체 교체 작업 이어서 진행','execute_plan':'검토한 저장 계획 실행'}.get(action,'작업'))
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
                    self.events.put(('progress',current_stage[0]+f' · AI 응답 대기 중 (요청 대기 설정 {ai.request_timeout_seconds}초)'))
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
            selected=value if action in ('deep','repair') else None
            if action=='replace_post':selected=value['post_id']
            if action.startswith('repair_image_') or action in ('repair_alt','repair_validate','repair_evidence','replace_all','replace_resume'):
                repair_row=store.db.execute('SELECT post_id FROM repair_proposals WHERE id=? AND blog_id=?',(value['proposal_id'],adapter.blog_id)).fetchone()
                if not repair_row:raise ValueError('수정안 기록 없음')
                selected=repair_row['post_id']
            from .cache_policy import force_whole_review
            self.sync_posts(store,adapter,adapter.blog_id,selected_post=selected);self.cancel_token.checkpoint(); run_checks(store,adapter.blog_id,force_recheck=selected is None and force_whole_review())
            if action in ('replace_post','replace_all','replace_resume'):
                from .replacement import Replacement
                from .bridge import WriteBridgeAdapter
                from .imagegen import Generator
                generator=Generator.from_environment();original_transport=generator.transport
                def guarded_replacement_image(request):
                    self.cancel_token.checkpoint();response=original_transport(request);self.cancel_token.checkpoint();return response
                generator.transport=guarded_replacement_image
                service=Replacement(store,WriteBridgeAdapter.from_environment(),ai,self.base/'image_cache',progress)
                if action=='replace_post':result=service.start_post(value['post_id'],value['topic'],generator)
                elif action=='replace_all':result=service.start(value['proposal_id'],value['topic'],generator)
                else:result=service.resume(value['proposal_id'],generator)
                if not result.get('replacement_preview_ready'):
                    task.finish('FAILED',json.dumps({**result.get('error_diagnostic',{}),'kind':'REPLACEMENT_HOLD','model':getattr(ai,'model',''),'stage':result.get('replacement_stage','생성 준비'),'summary':result.get('reason','생성 보류'),'action':'본문 검사·보완 기록에서 미통과 항목과 문장을 확인하고 같은 작업을 이어서 진행하세요.'},ensure_ascii=False))
                else:task.finish('COMPLETED')
                self.events.put(('repair_ready',result));return
            if action.startswith('repair_image_') or action in ('repair_alt','repair_validate','repair_evidence'):
                from .repair_images import RepairImages
                from .bridge import WriteBridgeAdapter
                service=RepairImages(store,WriteBridgeAdapter.from_environment(),ai,self.base/'image_cache',progress)
                try:
                    if action=='repair_validate':result=service.validate(value['proposal_id'])
                    elif action=='repair_evidence':result=service.repair_evidence(value['proposal_id'])
                    else:
                        generator=None
                        if action=='repair_image_generate':
                            from .imagegen import Generator
                            generator=Generator.from_environment();original_transport=generator.transport
                            def guarded_image(request):
                                self.cancel_token.checkpoint();response=original_transport(request);self.cancel_token.checkpoint();return response
                            generator.transport=guarded_image
                        op={'repair_image_import':'import','repair_image_generate':'generate','repair_alt':'alt','repair_image_choose':'choose','repair_image_cancel':'cancel'}[action]
                        result=service.operate(value['proposal_id'],op,value['slot'],value.get('path'),generator)
                except Cancelled:raise
                except Exception as error:
                    _,payload=service.load(value['proposal_id']);payload['reason']=str(error)
                    if getattr(error,'diagnostic',None):payload['error_diagnostic']=error.diagnostic
                    result=service.save(value['proposal_id'],payload)
                    finish_error(task,error);self.events.put(('repair_ready',result));return
                if action in ('repair_validate','repair_evidence'):
                    from .tasks import finish_validation
                    finish_validation(task,result)
                else:task.finish('COMPLETED')
                self.events.put(('repair_ready',result));return
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
                elif action=='apply_repair':result=Recovery(store,ai,writer,progress).apply_proposal(value['id'],expected_proposal_hash=value['expected'])
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
                    from .layout import upload_checked,recover_upload,upload_context
                    import uuid
                    writer=WriteBridgeAdapter.from_environment();payload=generation.load_job(value)['payload']
                    images=payload.get('image_candidates',[])
                    if len(images)!=2 or any(x.get('result')!='PASS' for x in images):raise ValueError('QA PASS 이미지 2장 필요')
                    receipts=payload.get('upload_receipts',[])
                    for index,image in enumerate(images):
                        if index<len(receipts):continue
                        requests=payload.setdefault('upload_requests',[])
                        context=upload_context(writer,image)
                        if index<len(requests):
                            request=requests[index]
                            if request.get('byte_hash')!=image['info']['byte_hash'] or request.get('upload_context',context)!=context:raise ValueError('기존 이미지 업로드 대상·파일 기록 불일치')
                            request['upload_context']=context
                            def record_upload(event):
                                request['recovery']=dict(event,image_slot=index+1)
                                generation.save(value,'이미지 업로드 결과 확인','HOLD',payload)
                            receipt=recover_upload(writer,image,request['id'],index+1,progress,record_upload)
                        else:
                            request_id=str(uuid.uuid4());requests.append({'id':request_id,'status':'SENDING','byte_hash':image['info']['byte_hash'],'upload_context':context})
                            generation.save(value,'이미지 업로드 요청','HOLD',payload)
                            receipt=upload_checked(writer,image,request_id)
                        receipts.append(receipt)
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
                    pack=collect_cached(store,ai,row['title'],row['title'],adapter.blog_id+':'+value+':'+row['content_hash'],progress,article=row['content'],allow_partial=True)
                except (GeminiError,EvidenceHold) as exc:
                    from .existing import partial_link_review,record_incomplete
                    partial=None
                    try:partial=partial_link_review(store,adapter,value,progress,ai=ai if isinstance(exc,EvidenceHold) else None,cache_dir=self.base/"image_cache")
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
                    try:partial=partial_link_review(store,adapter,value,progress,ai=ai if isinstance(exc,EvidenceHold) else None,cache_dir=self.base/"image_cache")
                    except Exception:pass
                incomplete=record_incomplete(store,adapter.blog_id,value,exc,partial)
                if incomplete:self.events.put(('inspection_incomplete',incomplete))
            finish_error(task,exc);self.events.put(('error',str(exc)))
        finally:
            if store: store.close()
    def start(self,force=False):
        if self.busy: return
        self.new_task();self.busy=True; self.button.config(state='disabled'); demo=self.demo.get()
        self.set_status(text='데모 조회 중…' if demo else 'Blogger LIVE / SCHEDULED / DRAFT 조회 중…')
        threading.Thread(target=self.worker,args=(demo,force),daemon=True).start()
    def worker(self,demo,force=False):
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
            from .cache_policy import force_whole_review
            sync=self.sync_posts(store,adapter,blog_id,force=force);self.cancel_token.checkpoint(); checks=run_checks(store,blog_id,force_recheck=force_whole_review(force=force))
            from .cache_policy import remember_checkpoint
            remember_checkpoint(store,blog_id,sync,checks)
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
                    self.set_status(text=event[1]);self.update_progress(event[1]); self.generation_notes.insert('end',event[1]+'\n'); self.generation_notes.see('end'); continue
                self.finish_progress(event)
                if self.task_outcome=='작업 종료' and (event[0] in ('google_done','publication_ready','ai_done','done') or (event[0]=='repair_ready' and (event[1].get('mode')!='REPLACEMENT' or event[1].get('replacement_preview_ready')))):
                    self.progress_bar.config(value=9)
                if event[0]=='google_done':
                    self.busy=False;self.button.config(state='normal');self.google_notes.delete('1.0','end')
                    for r in event[1]:
                        from .presentation import google_text
                        self.google_notes.insert('end',google_text(r))
                    self.set_status(text='Google 상태 기록 완료 · 색인 요청 제출 없음');continue
                if event[0]=='publication_ready':
                    self.busy=False;self.button.config(state='normal');self.generate_button.config(state='normal');self.show_publication(event[1],event[2]);continue
                if event[0]=='repair_ready':
                    self.busy=False;self.button.config(state='normal');self.generate_button.config(state='normal');self.show_repair(event[1]);self.set_status(text=event[1].get('reason','수정안 결과 확인'));continue
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
                    self.set_status(text='저장 기록 조회 완료 · 최신 Blogger 조회 없음' if local else '진단 완료 · 근거 보류 · 수정안 만들기로 이어가세요.' if isinstance(event[1],dict) and event[1].get('deep',{}).get('diagnostic_only') else '작업 종료 · 결과 기록 완료'); continue
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

