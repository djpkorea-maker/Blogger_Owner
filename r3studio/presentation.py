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
        try:
            import json
            detail=json.loads(row['details'])
        except (ValueError,TypeError,KeyError):detail=None
        if isinstance(detail,dict):
            for key,label in [('http_status','HTTP 오류 코드'),('reason','오류 분류'),('model','사용 모델'),('summary','원인'),('action','다음 조치'),('retry_after_seconds','재시도 대기(초)')]:
                if detail.get(key) is not None:lines.append(label+': '+str(detail[key]))
        elif row['status']=='FAILED':lines.append('이전 기록에는 상세 원인이 없습니다. 보완 버전으로 재검사해야 확인할 수 있습니다.')
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


def inspection_text(row):
    """Describe evidence actually present; absence must never imply a pass."""
    d=row.get('details') or {};fast=d.get('fast') or d
    metrics=fast.get('metrics',{});deep=d.get('deep') or {};review=deep.get('review') or {}
    lines=[f"글 번호: {row['post_id']}",f"상태: {row.get('status','')} / 검사 결과: {row['grade']}"]
    if row.get('title'):lines.append('제목: '+row['title'])
    lines.append('전체 검증: '+('완료' if d.get('verified') else '미완료 · 아직 검사하지 않은 항목을 통과로 보지 마세요.'))
    if row.get('status')=='SCHEDULED':lines.append('예약 보호: HOLD 표시는 Blogger의 실제 예약을 중지하지 않습니다.')
    if row['grade'].startswith('EMPTY'):
        lines.append('제목/본문 누락: 실제 Blogger 재조회 후 보관·복원·삭제 여부를 검토하세요. 자동 삭제하지 않습니다.')
    if metrics:
        lines.append(f"빠른 검사 완료: 본문 {metrics.get('text_length','?')}자 / 이미지 {metrics.get('images','?')}개 / 내부링크 {metrics.get('internal_links','?')}개 / 외부링크 {metrics.get('external_links','?')}개")
    labels={'fact':'사실 정확성','safety':'안전성','intent':'검색 의도','practical_value':'실용성','originality':'독창성'}
    states={'PASS':'통과','FAIL':'문제 발견','UNKNOWN':'확인 불가'}
    lines.append('본문 심층 검사: '+('완료 · '+ ' / '.join(labels[k]+': '+states.get(review.get(k),'확인 불가') for k in labels) if review else '미완료 · 결과 없음'))
    stages=d.get('check_states',{})
    lines.append('실제 이미지·ALT·설명 검사: '+stages.get('images', '완료' if d.get('images') else '미검사 · 이미지 개수만으로 품질을 판단할 수 없습니다.'))
    lines.append('링크 공개 접근 검사: '+stages.get('links','완료' if d.get('links',{}).get('pass') else '미검사 · 링크 개수와 실제 접근 검사는 별개입니다.'))
    issues=list(dict.fromkeys(list(fast.get('issues',[]))+list(d.get('issues',[]))+list(deep.get('issues',[]))))
    for claim in review.get('unsupported_claims',[]):issues.append('근거 부족 주장: '+str(claim))
    lines.append('\n확인할 문제와 다음 조치:')
    if not issues:lines.append('기록된 지적 없음 · 전체 검증 완료 여부는 위 항목을 확인하세요.')
    for issue in issues:
        lines.append('• '+str(issue))
        if issue=='내부링크 확인 필요':lines.append('  위치: 본문 전체에서 내부링크 0개 감지. 실제 공개된 관련 글을 선택하고 관련 설명 문장 뒤에 연결해야 합니다. 추천 글·삽입 문장은 아직 생성하지 않았습니다.')
        elif issue=='외부 근거 링크 확인 필요':lines.append('  본문 주장에 맞는 공식 근거 URL을 확인해 해당 설명 부분에 추가해야 합니다.')
        elif issue=='ALT 누락':lines.append('  ALT가 빈 이미지의 실제 픽셀을 확인하고 보이는 대상을 설명해야 합니다.')
    for finding in review.get('findings',[]):
        lines.extend(['\n문제 위치: '+finding['location'],'문제 내용: '+finding['excerpt'],'이유: '+finding['reason'],'수정 제안: '+finding['suggestion']])
    if review and issues and not review.get('findings'):lines.append('세부 문제 위치가 응답에 없습니다. 심층 재검사 또는 수정안 검토가 필요합니다.')
    if d.get('error_diagnostic'):
        error=d['error_diagnostic'];lines.append('검사 실패 원인: '+error.get('summary','확인 필요')+' / '+error.get('action','작업 기록 확인'))
    if not d.get('verified'):lines.append('\n다음: 연결 오류가 있으면 먼저 해결 → 선택 글 심층 검사 → 수정안 만들기 → 변경 내용 검토')
    return '\n'.join(lines)
