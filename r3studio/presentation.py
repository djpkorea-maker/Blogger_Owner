"""Small, safe summaries for the desktop UI; raw payloads stay in the database."""
LABELS={'HOLD':'보류','PASS':'검사 통과','RUNNING':'진행 중','VERIFIED':'저장 결과 확인 완료','LIVE':'공개 발행','DRAFT':'초안 저장','SCHEDULED':'예약 저장','CANCELLED':'사용자 중단','FAILED':'오류로 중단','COMPLETED':'작업 완료','NEEDS_RECONCILE':'실제 저장 결과 재확인 필요'}
def result_text(value):
    if isinstance(value,list):
        return '\n\n'.join(result_text(v) for v in value) or '표시할 작업이 없습니다.'
    if not isinstance(value,dict):return '작업 결과가 기록되었습니다.'
    payload=value.get('payload') if isinstance(value.get('payload'),dict) else {}
    lines=[]
    for key,label in [('job_id','생성 작업 번호'),('id','작업 번호'),('title','제목'),('topic','주제'),('stage','현재 단계'),('status','결과'),('grade','검사 판정'),('post_id','Blogger 글 번호'),('audit_id','저장 기록 번호'),('url','글 주소')]:
        item=value.get(key)
        if item is not None and item!='':lines.append(f'{label}: {LABELS.get(item,item) if key=="status" else item}')
    if value.get('issues'):lines.append('확인할 사항: '+' / '.join(str(x) for x in value['issues']))
    reason=value.get('reason') or payload.get('reason')
    if reason:lines.append('안내: '+str(reason))
    if value.get('status')=='HOLD':lines.append('이 상태에서는 발행할 수 없습니다.')
    if value.get('local_only'):lines.append('저장 기록 조회 · 최신 Blogger 상태는 아직 확인하지 않았습니다.')
    if value.get('unreadable_related_records'):lines.append('관련 수정안 기록 '+str(value['unreadable_related_records'])+'개를 읽을 수 없어 그대로 보존했습니다. 확인된 Blogger 저장 결과는 유지됩니다.')
    return '\n'.join(lines) or '작업 결과가 기록되었습니다.'

def history_text(rows):
    lines=[]
    for row in rows:
        status='종료 미확인 · 이전 작업 상태 확인 필요' if row['status']=='RUNNING' else LABELS.get(row['status'],row['status'])
        lines.append(f"기록 {row['id']} · {row['task']} · {status}\n시작: {row['started_at']} / 종료: {row['finished_at'] or '미확인'}")
    return '\n\n'.join(lines) or '저장된 작업 기록이 없습니다.'

def inspection_summary(sync,checks,rows,demo=False):
    from collections import Counter
    counts=Counter(row['grade'] for row in rows)
    grades=' / '.join(f'{grade} {counts[grade]}' for grade in ('PASS','A','B','C','SCHEDULED_PASS','SCHEDULED_HOLD') if counts[grade])
    empty=sum(n for grade,n in counts.items() if grade.startswith('EMPTY'))
    pending=sum(n for grade,n in counts.items() if grade in ('NEEDS_DEEP','NEEDS_EVIDENCE','TEXT_PASS_IMAGE_PENDING','INCOMPLETE_DRAFT'))
    return f"{'데모 · ' if demo else ''}조회 {sync['listed']} / 변경 {sync['changed']} / 본문 재사용 {sync['reused']} / 검사 {checks['checked']} / 검사 재사용 {checks['reused']}\n"+(grades+' / ' if grades else '')+f'누락 {empty} / 검증 미완료 {pending}'

def google_text(result):
    technical={'ACCESSIBLE':'공개 접근 가능','404':'페이지 없음 (404)','SERVER_ERROR':'서버 오류','HTTP_ERROR':'접근 오류','NOINDEX':'검색 색인 제한 발견','REDIRECT':'다른 주소로 이동','CANONICAL_REVIEW':'대표 주소 확인 필요','FETCH_FAILED':'공개 접근 확인 실패'}
    crawl_labels={'ALLOWED':'허용','BLOCKED':'차단','NO_FILE_NO_RESTRICTION':'파일 없음 · 차단 규칙 없음','UNKNOWN':'확인 불가','FOUND':'URL 포함 확인','NOT_LISTED':'조회한 sitemap에 URL 없음','UNKNOWN_OR_PARTIAL':'전체 확인 불가'}
    crawl=result.get('public_crawl',{})
    lines=[result.get('title','제목 없음'),result.get('url',''),
           '공개 접근: '+technical.get(result['technical_status'],result['technical_status']),
           'Google 색인: '+result['index_status']]
    if result.get('http_status') is not None:lines.append('HTTP 응답: '+str(result['http_status']))
    if result.get('redirects'):lines.append('이동한 주소: '+result.get('final_url','확인 불가'))
    lines.append('대표 주소: '+(' / '.join(result.get('canonical',[])) or '페이지에 선언 없음'))
    lines.append('공개 robots: '+crawl_labels.get(crawl.get('robots_state'),'확인 불가'))
    lines.append('sitemap: '+crawl_labels.get(crawl.get('sitemap_state'),'확인 불가'))
    lines.append('이전 검사 대비: '+('첫 검사' if result.get('first_check') else '변화 있음' if result.get('changed') else '변화 없음'))
    if result.get('new_problem'):lines.append('새로 발견한 문제 · 우선 확인 필요')
    if result.get('persistent_problem'):lines.append('이전 검사부터 계속 남아 있는 문제')
    if result.get('resolved_problems'):lines.append('이전에 발견한 문제 일부 또는 전체 해소 · 현재 결과 확인 필요')
    if result.get('previous_record_unusable'):lines.append('이전 기록을 읽을 수 없어 새로 검사함 · 이전 상태 비교 불가')
    if result.get('console_error'):lines.append('Search Console 조회 실패 · 공개 접근 결과와 색인 확인을 구분하세요.')
    if result.get('reused'):lines.append('최근 검사 기록 재사용')
    return '\n'.join(lines)+'\n\n'

def google_sort_key(result):
    priority=0 if result.get('new_problem') else 1 if result.get('changed') else 2 if result.get('needs_attention') else 3
    return priority,result.get('title','')
