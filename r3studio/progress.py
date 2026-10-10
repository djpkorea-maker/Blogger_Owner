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
