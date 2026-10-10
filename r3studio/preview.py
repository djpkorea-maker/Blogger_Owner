"""Read-only native article preview. HTML scripts and links are never executed."""
import io
import queue
import threading
from html.parser import HTMLParser
from pathlib import Path
from PIL import Image
from .images import ImageHold,inspect_bytes,public_image_bytes

class PreviewParts(HTMLParser):
    def __init__(self,content):
        super().__init__();self.parts=[];self.hidden=0;self.image_index=0;self.feed(content)
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','iframe','object','template'):self.hidden+=1;return
        if self.hidden:return
        if tag=='img':
            self.image_index+=1
            self.parts.append({**dict(attrs),'kind':'image','index':self.image_index})
        elif tag in ('p','div','figure','figcaption','h1','h2','h3','li','br','tr'):
            self.parts.append({'kind':'text','text':'\n'})
    def handle_startendtag(self,tag,attrs):self.handle_starttag(tag,attrs)
    def handle_endtag(self,tag):
        if tag in ('script','style','iframe','object','template'):self.hidden=max(0,self.hidden-1)
        elif not self.hidden and tag in ('p','div','figure','figcaption','h1','h2','h3','li','tr'):
            self.parts.append({'kind':'text','text':'\n'})
    def handle_data(self,data):
        if not self.hidden:self.parts.append({'kind':'text','text':data})

def preview_parts(content,reviews=(),proposed=False,choices=None):
    """Display stored HTML attributes separately from unapplied AI suggestions."""
    from .captions import image_captions
    parts=PreviewParts(content).parts
    try:captions=image_captions(content)
    except ImageHold:captions=[]
    by_index={i.get('index'):i for i in reviews if isinstance(i,dict)}
    for part in parts:
        if part['kind']!='image':continue
        index=part['index'];review=by_index.get(index,{})
        # Never attach a review to an image with a different URL.
        if review.get('url')!=part.get('src'):review={}
        part['caption']=captions[index-1] if index<=len(captions) else ''
        part['caption_uncertain']=not bool(part['caption'])
        part['preview_file']=review.get('preview_file','');part['pixel_hash']=review.get('pixel_hash','')
        choice=(choices or {}).get(str(index),{}) if proposed else {}
        if choice and choice.get('expected_url')==part.get('src'):
            candidate=choice.get('candidate',{})
            if candidate.get('result')=='PASS' or choice.get('preview_only') and candidate.get('result')=='HOLD' and candidate.get('file') and candidate.get('info'):
                part.update(alt=candidate.get('alt',''),caption=candidate.get('caption',''),caption_uncertain=not bool(candidate.get('caption')),candidate_status=candidate['result'],preview_only=choice.get('preview_only',False),
                    preview_file=candidate['file'],pixel_hash=candidate['info']['pixel_hash'],selected_candidate=True)
        suggestion={} if part.get('selected_candidate') else review.get('suggested_text',{})
        if proposed and isinstance(suggestion,dict):
            pending={key:suggestion[key] for key in ('alt','caption')
                if isinstance(suggestion.get(key),str) and suggestion[key]!=part.get(key,'')}
            if pending:part['pending_text']=pending
    return parts

def thumbnail_bytes(url,cache_dir,review=None,download=public_image_bytes):
    """Reuse only a matching checked pixel file; downloads stay off the UI thread."""
    review=review or {};data=None
    local=review.get('preview_file','')
    if local and review.get('pixel_hash'):
        path=Path(local);base=Path(cache_dir).resolve()
        try:
            if path.resolve().parent==base and path.stat().st_size<=2*1024*1024:
                candidate=path.read_bytes()
                if inspect_bytes(candidate)['pixel_hash']==review['pixel_hash']:data=candidate
        except (OSError,ValueError,ImageHold):pass
    if data is None:data=download(url)
    inspect_bytes(data)
    with Image.open(io.BytesIO(data)) as im:
        im=im.convert('RGB');im.thumbnail((420,260));out=io.BytesIO();im.save(out,format='PNG');return out.getvalue()

def show_article_comparison(dialog,panes,original,proposed,reviews,cache_dir,download=public_image_bytes,choices=None,image_number=None,labels=('현재 글','수정안')):
    """Create ordered text/pixel previews and asynchronously fill image placeholders."""
    import tkinter as tk
    from tkinter import ttk
    from tkinter.scrolledtext import ScrolledText
    from PIL import ImageTk
    events=queue.Queue();targets={};image_refs=getattr(dialog,"preview_image_refs",[]);widgets=[];parts_by_side=[]
    dialog.preview_image_refs=image_refs;dialog.preview_widgets=getattr(dialog,"preview_widgets",[])
    for side,(label,content) in enumerate(((labels[0],original),(labels[1],proposed))):
        frame=ttk.Frame(panes);panes.add(frame,weight=1)
        ttk.Label(frame,text=label,font=('',13,'bold')).pack(anchor='w')
        parts=preview_parts(content,reviews,proposed=bool(side),choices=choices);parts_by_side.append(parts)
        count=sum(part['kind']=='image' for part in parts)
        ttk.Label(frame,text=f'본문 이미지 {count}개 · ALT와 그림 설명을 아래에서 확인하세요.').pack(anchor='w')
        text=ScrolledText(frame,wrap='word',width=45);text.pack(fill='both',expand=True);widgets.append(text)
        text.tag_configure('image_meta',foreground='#24527a')
        text.tag_configure('pending',foreground='#995500')
        if not content:text.insert('end','수정 본문이 아직 생성되지 않았습니다.\n')
        for part in parts:
            if part['kind']=='text':text.insert('end',part['text']);continue
            text.insert('end',f"\n\n[이미지 {image_number or part['index']}]\n",'image_meta')
            placeholder=ttk.Label(text,text='이미지 불러오는 중…')
            text.window_create('end',window=placeholder);text.insert('end','\n')
            key=(part.get('src',''),part.get('pixel_hash',''),part.get('preview_file',''))
            targets.setdefault(key,[]).append(placeholder)
            if part.get('selected_candidate'):text.insert('end',('미통과 후보 · 교체 불가' if part.get('candidate_status')=='HOLD' else '검토할 후보' if part.get('preview_only') else '선택한 후보')+' · 최종 검증 전 · Blogger 미반영\n','pending')
            text.insert('end','ALT: '+(part.get('alt') or '(없음)')+'\n','image_meta')
            text.insert('end','그림 설명: '+(part['caption'] or '(HTML에서 이미지별 연결 미확인 · 본문의 설명 문장도 확인하세요.)')+'\n','image_meta')
            for key,value in part.get('pending_text',{}).items():
                text.insert('end',('ALT' if key=='alt' else '그림 설명')+' 수정 제안 · 아직 미반영: '+value+'\n','pending')
            text.insert('end','\n')
        text.config(state='disabled')
    dialog.preview_widgets.extend(widgets)
    def worker():
        parts=[p for side in parts_by_side for p in side if p['kind']=='image']
        for key in targets:
            url=key[0]
            try:
                part=next(p for p in parts if (p.get('src',''),p.get('pixel_hash',''),p.get('preview_file',''))==key)
                events.put((key,thumbnail_bytes(url,cache_dir,part,download),None))
            except Exception:
                events.put((key,None,'이미지 표시 실패 · ALT와 설명은 확인할 수 있습니다.'))
    remaining=set(targets)
    def poll():
        if not dialog.winfo_exists():return
        try:
            while True:
                key,data,error=events.get_nowait();remaining.discard(key)
                photo=None
                if data:
                    with Image.open(io.BytesIO(data)) as im:photo=ImageTk.PhotoImage(im.copy(),master=dialog)
                    image_refs.append(photo)
                for target in targets[key]:
                    if target.winfo_exists():target.config(image=photo or '',text=error or '')
        except queue.Empty:pass
        if remaining:dialog.master.after(100,poll)
    if targets:
        threading.Thread(target=worker,daemon=True).start();dialog.master.after(100,poll)
    return widgets
