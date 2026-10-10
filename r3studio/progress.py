"""Static stage position. Never infer a percentage from AI waiting or item counts."""
import re
STAGES=(('조회','동기화'),('빠른 검사','Fast'),('Evidence','근거 검색','검색 출처','기존 근거'),('근거 장부',),('근거 원문',),('본문','심층','Fact','Quality'),('이미지',),('링크',))
def progress_state(text):
    waiting='응답 대기' in text
    count=re.search(r'(\d+)/(\d+)\s*$',text)
    current,total=(int(count[1]),int(count[2])) if count else (0,0)
    return {'waiting':waiting,'mode':'determinate','current':min(current,total) if total else 0,'total':total,'label':'AI 응답 대기 · 완료율 확인 불가' if waiting else '현재 단계의 항목 진행' if total else '현재 단계 처리 중'}
class StageProgress:
    def __init__(self):self.position=0
    def update(self,text):
        for i,words in enumerate(STAGES,1):
            if any(word in text for word in words):
                self.position=max(self.position,i);break
        return self.position

def terminal_summary(event):
    """Completion is different from validation success; HOLD stays incomplete."""
    kind=event[0];result=event[1] if len(event)>1 else None
    if kind=='error':return '오류 종료 · '+str(result)
    rows=result if isinstance(result,list) else [result]
    for row in rows:
        if isinstance(row,dict) and (row.get('status') in ('HOLD','NEEDS_RECONCILE','RUNNING') or row.get('grade') in ('HOLD','SCHEDULED_HOLD','NEEDS_DEEP') or row.get('deep',{}).get('diagnostic_only')):
            return '보류 종료 · '+str(row.get('reason') or '검증 미완료 · 결과 확인 필요')
    if kind=='repair_ready' and isinstance(result,dict) and result.get('mode')=='REPLACEMENT' and not result.get('replacement_preview_ready'):
        return '보류 종료 · '+str(result.get('reason') or '새 본문 미작성')
    return '작업 종료 · 결과 확인 가능'
