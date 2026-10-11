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
            for key,label in [('http_status','HTTP 오류 코드'),('reason','오류 분류'),('server_code','Bridge 거절 코드'),('server_status','서버 업로드 상태'),('image_slot','이미지 번호'),('model','사용 모델'),('summary','원인'),('action','다음 조치'),('retry_after_seconds','재시도 대기(초)'),('stage','중단 단계'),('request_type','요청 종류'),('elapsed_seconds','해당 요청 대기(초)'),('timeout_seconds','요청 대기 설정(초)'),('input_chars','요청 자료 길이(문자)'),('thinking_level','검색 사고 설정')]:
                if detail.get(key) is not None:lines.append(label+': '+str(detail[key]))
            lines.extend(diagnostic_lines(detail))
        elif row['status']=='FAILED':lines.append('이전 기록에는 상세 원인이 없습니다. 보완 버전으로 재검사해야 확인할 수 있습니다.')
    return '\n\n'.join(lines) or '저장된 작업 기록이 없습니다.'

def inspection_summary(sync,checks,rows,demo=False):
    from collections import Counter
    counts=Counter(row['grade'] for row in rows)
    grades=' / '.join(f'{grade} {counts[grade]}' for grade in ('PASS','A','B','C','SCHEDULED_PASS','SCHEDULED_HOLD') if counts[grade])
    empty=sum(n for grade,n in counts.items() if grade.startswith('EMPTY'))
    pending=sum(n for grade,n in counts.items() if grade in ('NEEDS_DEEP','NEEDS_EVIDENCE','TEXT_PASS_IMAGE_PENDING','INCOMPLETE_DRAFT'))
    if sync.get('full_test_review'):
        return f"시험판 전체 재검사 · 조회 {sync['listed']} / 본문 새로 조회 {sync['refetched']} / 실제 변경 {sync['changed']} / Fast 재검사 {checks['checked']} / 검사 재사용 {checks['reused']}\n"+(grades+' / ' if grades else '')+f'누락 {empty} / 검증 미완료 {pending} · AI 심층 검사는 별도 선택'
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
    if metrics.get('text_length') is not None:
        lines.append(f"빠른 검사 완료: 본문 {metrics.get('text_length','?')}자 / 이미지 {metrics.get('images','?')}개 / 내부링크 {metrics.get('internal_links','?')}개 / 외부링크 {metrics.get('external_links','?')}개")
    labels={'fact':'사실 정확성','safety':'안전성','intent':'검색 의도','practical_value':'실용성','originality':'독창성'}
    states={'PASS':'통과','FAIL':'문제 발견','UNKNOWN':'확인 불가'}
    lines.append('본문 심층 검사: '+(('진단 기록 완료 · 근거 보류 · ' if deep.get('diagnostic_only') else '완료 · ')+ ' / '.join(labels[k]+': '+states.get(review.get(k),'확인 불가') for k in labels) if review else '미완료 · 결과 없음'))
    if d.get('evidence_diagnostic'):
        lines.append('근거 확인 보류: '+d['evidence_diagnostic'].get('summary',''))
        lines.extend(diagnostic_lines(d['evidence_diagnostic']))
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
    for item in d.get('image_review',{}).get('items',[]):
        lines.append('\n이미지 '+str(item['index'])+' · '+item['status'])
        if item.get('observed'):lines.append('실제 보이는 대상: '+item['observed'])
        lines.extend('• '+issue for issue in item.get('issues',[]))
        if item.get('replacement_needed'):lines.append('조치: 본문에 맞는 이미지 교체 필요 · 자동 교체하지 않았습니다.')
        suggestion=item.get('suggested_text')
        if suggestion:
            lines.append('현재 ALT: '+item['current_alt']);lines.append('ALT 수정 제안: '+suggestion['alt']);lines.append('설명문 수정 제안: '+suggestion['caption'])
            lines.append('이 제안은 적용 전 최종 픽셀 일치 재검증이 필요합니다.')
    if d.get('image_error_diagnostic'):
        lines.extend(diagnostic_lines(d['image_error_diagnostic']))
    access=d.get('link_access')
    if isinstance(access,dict):
        lines.append('\n링크별 공개 접근 결과 · 사실 근거 적합성과는 별도:')
        labels_access={'ACCESSIBLE':'접근 가능','HTTP_ERROR':'HTTP 오류','FETCH_FAILED':'조회 실패','INVALID_URL':'주소 형식 오류'}
        for item in access.get('results',[]):
            lines.append('• '+item['url']+' → '+labels_access.get(item['state'],item['state'])+(' ('+str(item['http_status'])+')' if 'http_status' in item else ''))
        if not access.get('results'):lines.append('검사할 본문 링크 없음')
    if d.get('error_diagnostic'):
        error=d['error_diagnostic'];lines.append('검사 실패 원인: '+error.get('summary','확인 필요')+' / '+error.get('action','작업 기록 확인'))
        lines.extend(diagnostic_lines(error))
    if not d.get('verified'):lines.append('\n다음: 실패 원인·미검증 문장 확인 → 근거와 표현을 보완한 수정안 만들기 → 변경 내용 검토 → 최종 재검증')
    return '\n'.join(lines)


def diagnostic_lines(detail):
    lines=[]
    if detail.get('fact_search_attempts'):
        from .fact_search import diagnostic_lines as search_lines
        lines.extend(search_lines(detail['fact_search_attempts']))
    if detail.get('image_generation_started') is not None:
        lines.append('이미지 생성 API 호출: '+('시작됨' if detail['image_generation_started'] else '아직 시작하지 않음'))
    if detail.get('text_review'):
        from .text_flow import review_lines
        lines.extend(review_lines(detail['text_review']))
    checked=detail.get('verification_counts',{})
    from .source_domains import claims_not_evaluated
    pending=claims_not_evaluated(detail)
    if checked and pending:
        lines.append('문장별 지원 판정: 미실시 · 출처·접근·응답 형식 단계에서 종료')
        lines.append('검증 대기 문장: '+str(checked.get('pending_facts',checked.get('listed_facts','미확인')))+'개 · 지원 0개 판정이 아닙니다.')
    elif checked:
        lines.append('원문 근거 판정: 장부 '+str(checked.get('listed_facts','미확인'))+
            '개 / 지원 확인 '+str(checked.get('supported_facts','미확인'))+
            '개 / 프로그램 기준 '+str(checked.get('minimum_supported_facts',4))+
            '개 / 미검증 '+str(checked.get('unverified_facts','미확인'))+'개')
        lines.append('이 개수는 프로그램 내부 기준이며 승인 여부나 사실 오류 판정이 아닙니다.')
    independence=detail.get('source_independence',{})
    if independence:
        lines.append('독립 출처 검사: A/B 원문 '+str(independence.get('trusted_sources',0))+
            '개 / 발행 주체 '+str(independence.get('publishers',0))+
            '개 / 등록 도메인 '+str(independence.get('registered_domains',0))+'개 · 각각 최소 2개')
        if independence.get('missing'):lines.append('부족한 출처 조건: '+' / '.join(independence['missing']))
        for source in independence.get('sources',[]):
            lines.append('출처 판정: '+source['url']+' / '+source['grade']+' / '+source['publisher']+
                ' / 등록 도메인 '+(source['registered_domain'] or '확인 불가')+
                (' / 계산에 포함' if source.get('counted') else ' / A/B 원문·발행 주체·주소 확인 필요'))
    retry=detail.get('original_recheck',{})
    if retry:
        lines.append('같은 원문 대조 재검사: '+str(retry.get('used',0))+
            '/'+str(retry.get('limit',1))+'회 · '+retry.get('state','확인 필요')+' · 본문·이미지 보존')
    counts=detail.get('coverage',{})
    if counts:
        lines.append(f"본문 작성용 실제 근거: 목록 {counts['listed_sources']}개 / 원문 확보 {counts['fetched_sources']}개 / 지원 연결 {counts['used_sources']}개 / 독립 도메인 {counts['used_domains']}개")
        lines.append(f"원문 지원 사실 {counts['supported_facts']}개 / 핵심 {counts['core_facts']}개 / 실용 {counts['practical_facts']}개 / 조건 {counts['condition_facts']}개")
    if 'supplemental_searches' in detail:
        lines.append('부족한 근거 추가 검색: '+str(detail['supplemental_searches'])+'/1회')
    for source in detail.get('supplemental_source_checks',[]):
        lines.append('추가 원문: '+source['url']+' / '+source['state']+(' / '+source['reason'] if source.get('reason') else ''))
    if detail.get('response_shape_issues'):
        lines.append('원문 검사 응답 형식 문제 · 사실 정확성 판정과 별도:')
        lines.extend('• '+issue for issue in detail['response_shape_issues'])
    for attempt in detail.get('response_format_attempts',[]):
        state='형식 확인 완료 · 사실 검증은 별도' if attempt.get('state')=='VALID_SHAPE' else '형식 오류'
        lines.append('원문 검사 응답 '+str(attempt['attempt'])+'차: '+state)
        lines.extend('• '+issue for issue in attempt.get('issues',[]))
    if detail.get('format_recovery_exhausted'):lines.append('같은 원문 형식 재검사 1회 한도 종료 · 본문 작성·발행 불가')
    if detail.get('missing_criteria'):lines.append('부족한 검사 기준: '+detail['missing_criteria'])
    budget=detail.get('research_budget',{})
    if budget:
        lines.append(f'실행 횟수: 검색 {budget["searches"]}/{budget["search_limit"]} · 기존 자료 장부 보완 {budget["ledger_repairs"]}/{budget["repair_limit"]}')
    if detail.get('recovery_exhausted'):lines.append('이번 오류에 대한 자동 복구 한도 종료 · 현재 실행 중인 복구 없음')
    ledger=detail.get('ledger',{})
    if ledger:
        lines.append('근거 장부 상태: '+('AI 응답 형식·분류 보완 필요' if ledger.get('state')=='FORMAT' else '근거 연결·핵심 사실 분류 확인 필요'))
        if 'linked_facts' in ledger:lines.append(f'AI 장부의 근거 연결 사실 {ledger["linked_facts"]}개 / 핵심 분류 {ledger["core_facts"]}개 · 원문 검증 통과와 별도')
        lines.extend('• '+issue for issue in ledger.get('issues',[]))
        lines.extend('장부 사실: '+f['text']+' / 핵심 분류: '+str(f.get('core'))+' / 유형: '+str(f.get('kind')) for f in ledger.get('facts',[]))
    role=detail.get('condition_role_review',{})
    if role:
        lines.append('조건·예외 분류 재확인: '+str(role.get('state','미확인'))+' · 1회 한도 · 사실 지원은 별도 원문 검증')
        lines.extend('조건 구절: '+c['excerpt'] for c in role.get('changes',[]))
    if 'condition_facts' in ledger:
        lines.append('AI 장부 유형: 실용 '+str(ledger.get('practical_facts',0))+'개 / 조건·예외 '+str(ledger['condition_facts'])+'개 · 원문 지원 판정과 별도')
    research=detail.get('research_claims_only') is True
    for claim in ([] if pending and not research else detail.get('unverified_claims',[])):
        lines.append(('검색 단계 근거 연결 미확보 문장: ' if research else '근거 미확보 주장: ')+claim['text']+' / '+claim['reason'])
        checked_claim=next((c for c in detail.get('claim_checks',[]) if c.get('text')==claim['text']),{})
        if checked_claim.get('source_urls'):
            lines.append('이 주장에 연결된 원문: '+' / '.join(checked_claim['source_urls']))
    targets=detail.get('verification_targets') or ([c.get('text','') for c in detail.get('unverified_claims',[])] if pending else [])
    if targets and (pending or not detail.get('unverified_claims')):
        lines.append('검증 대상으로 전달한 본문 문장 · 개별 근거 판정 미완료:')
        lines.extend('• '+text for text in targets)
    for key,label in [('existing_urls','본문의 기존 링크'),('search_urls','실제 검색 출처'),('unmatched_urls','AI가 제시한 불일치 출처')]:
        if detail.get(key):
            lines.append(label+' · 표시에서는 주소의 질의값·앵커 제외:')
            lines.extend('• '+url for url in detail[key])
    for source in detail.get('source_checks',[]):
        lines.append('원문 접근: '+source['url']+' / '+source['state']+(' / '+source['reason'] if source.get('reason') else ''))
    for attempt in detail.get('search_attempts',[]):
        lines.append('검색 복구 기록: '+attempt['reason']+(' / '+str(attempt['elapsed_seconds'])+'초' if attempt.get('elapsed_seconds') is not None else ''))
    for attempt in detail.get('attempts',[]):
        state={'PLANNED':'예정','STARTED':'요청 시작 · 완료 미확인','EXECUTED':'실행 완료 · 통과 여부와 별도','FAILED':'실행 실패'}.get(attempt.get('recovery_state'),'이전 기록 · 실행 여부 미기록')
        lines.append('근거 조사 '+str(attempt['attempt'])+'차: '+attempt['reason']+(' / '+attempt['operation'] if attempt.get('operation') else '')+(' / '+attempt['recovery']+' ['+state+']' if attempt.get('recovery') else ''))
    return lines
