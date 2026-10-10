"""Truthful stage position; AI response completion percentage is unknown."""
import re

def progress_state(text):
    waiting='응답 대기' in text
    count=re.search(r'(\d+)/(\d+)\s*$',text)
    current,total=(int(count[1]),int(count[2])) if count else (0,0)
    return {'waiting':waiting,'mode':'determinate' if total and not waiting else 'indeterminate','current':min(current,total) if total else 0,'total':total,'label':'AI 응답 대기 · 완료율 확인 불가' if waiting else '현재 단계의 항목 진행' if total else '현재 단계 처리 중'}
