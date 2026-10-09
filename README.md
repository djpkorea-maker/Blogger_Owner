# R3.0 Blogger 통합 스튜디오 — 설계 고정 및 1단계 개발본
## 최신 재개 상태 — 0.59 (2026-10-10)

58번 저장본에서 개발을 재개했습니다. 아래 과거 버전 기록보다 이 상태와 RELEASE_STATUS_KO.md가 우선합니다.

- 공개 글·예약·초안을 최신 Blogger 조회로 점검하며 기존 글 품질 개선과 신규 생성에 사용합니다.
- LIVE 동기화의 글별 진행 표시·요청 사이 중단 확인을 추가했습니다. 중단 시 기존 DB 원본을 유지합니다.
- 기존 글 검사는 대상 글과 LIVE 관계 글을 비교합니다. 관계없는 다른 초안 변경은 신규 검사 기록의 PASS를 무효화하지 않습니다. LIVE 변경 보호와 최종 발행 전 전체 목록 검사는 유지합니다.
- 제목 프로파일(핵심 질문·검색 의도·예상 H2·핵심 사실·실용 결론)의 의미 중복 검사, Title Refill 후 재검사와 작성 후 본문 의미 중복 검사를 추가했습니다. 불확실 응답은 HOLD입니다.
- 사실·안전·품질 실패 글의 자동 이미지 생성 비용을 사전 차단합니다.
- Windows 빌드는 수동 실행 또는 main 코드 변경으로 실행하며, 실제 생성 EXE에서 3탭 UI 구성과 DPAPI 왕복을 네트워크 없이 검사합니다. 사용자 PC 실사용/실계정 통합 검증은 별도입니다.
- 기존 글 이미지 교체 UI, Blogger 검색설명 실제 저장, Search Console 로그인/토큰 자동 갱신 및 실계정 시험은 남아 있습니다. 단순 형식 정상만으로 최종 PASS를 부여하지 않습니다.

기준일: 2026-10-09

## 현재 상태
SQLite 및 읽기 전용 LIVE Sync 핵심 코드 구현. 모의 연결 테스트 통과.
실제 Blogger 어댑터, UI, 생성 엔진, AI 검사, Google 연결, 배포본은 미구현이다.
이 파일은 완성 프로그램이나 Windows 실행 파일이 아니다.

## 고정 원칙
LIVE First / Cache First / Changed Only / AI Only When Needed / Apply Safely.
화면은 기존 글 조회·점검 / 새 글 생성 / Google 상태 감시의 세 메뉴.
전체 LIVE/SCHEDULED/DRAFT 메타데이터를 매번 페이지 끝까지 읽고 신규·변경 글만 본문 조회.
전체 재검사는 기본 동작에서 제외한다. 검사 규칙 버전 변경이나 사용자의 명시적 재검사는 예외로 기록한다.
Recovery JSON은 참고 데이터이며 LIVE를 덮어쓰지 않는다.

## 판정 및 근거
기존 LIVE: PASS/A/B/C. 예약: SCHEDULED_PASS/SCHEDULED_HOLD.
이상: EMPTY_TITLE/EMPTY_BODY/EMPTY_BOTH/INCOMPLETE_DRAFT.
동기화 직후에는 NEEDS_REVIEW/SCHEDULED_NEEDS_REVIEW로 표시한다. 동기화만으로 PASS를 부여하지 않는다.
A/B/C 의미와 임계값은 2단계에서 고정하며 보완 난이도와 오류 심각도를 함께 표시한다.
Fast Gate는 형식적 통과와 사실 검증을 구분한다. 기술·안전 주장에 충분한 근거가 없으면 Deep Gate 또는 HOLD로 보낸다.
새 글은 1개 기본, 최대 3개. PASS만 발행/예약 가능하며 HOLD는 발행하지 않는다.
이미지 의미 검사는 실제 픽셀을 입력으로 받아야 한다. 이미지 URL hash는 픽셀 hash가 아니다.
현 코드 image_hash는 이미지 URL 목록의 hash이며, 실제 픽셀 hash와 다운로드 검사일은 이미지 단계에서 별도로 추가한다.

## DB와 동기화 계약
핵심 7테이블: posts/post_versions/recovery_checks/generation_history/image_checks/google_status/apply_history.
운영 테이블 sync_runs 추가. blog_id+post_id로 블로그 간 ID 충돌 방지.
updated 또는 상태가 달라지면 본문 재조회, 기존 등급 무효화, 새 버전 보존.
목록과 본문 updated 불일치면 전체 동기화 반영을 중지하고 재시도한다.
목록 또는 상세 조회 실패 시 기존 posts를 유지한다. 모든 조회 성공 후 하나의 DB 트랜잭션으로 반영한다.
완전 조회에서 사라진 글은 present=0으로 표시하며 기록을 삭제하지 않는다.
현 list_metadata 어댑터 계약은 전체 ADMIN 목록 완전 조회를 요구한다. 실제 어댑터에서는 상태별 페이지 조회와 완료 여부 검증을 구현한다.
메타데이터 변경 없음은 현재 콘텐츠 캐시 재사용 근거다. 외부 이미지 파일 교체나 검사규칙 변경까지 보증하지 않으므로 별도 유효기간과 버전 키가 필요하다.

## Bridge 검토 결과
첨부 마크다운은 Recovery Bridge R2이고 텍스트는 V23 FINAL FIXED10B Evidence-First SEARCH-2PASS R6D4.2 V2 TITLE-REFILL RESEARCH-RECOVERY이다.
Bridge에는 조회/Drive 백업/PATCH/롤백/발행/이미지 업로드가 있다.
현재 export는 fetchBodies=true로 전체 본문을 가져와 Drive JSON 파일을 만든다. 메타데이터 API 응답 경로와 단건 GET 경로를 추가해야 한다.
현재 apply_update는 expectedUrl을 확인하지만 expectedHash는 확인하지 않는다.
Markdown의 역슬래시 이스케이프를 정리한 후 Apps Script 문법 검증이 필요하다.
기준 파일의 인증값은 새 코드·배포 ZIP·로그에 포함하지 않는다. 배포 시 Script Properties와 사용자 로컬 보안 설정을 사용한다.

## 안전 적용 설계
작업 시작 시 원본 hash 및 updated 보존 → Bridge에서 직전 GET 비교 → 충돌 시 중지 → 백업 → PATCH → GET 재검증 → 이력 기록.
Bridge 잠금은 Bridge 작업끼리만 직렬화한다. 사람이 Blogger 화면에서 수정하는 경쟁까지 막는 원자적 보장은 아니다.
API의 조건부 갱신 지원 여부를 공식 문서와 실제 연결로 확인하고, 미지원 시 남는 경쟁 가능성을 UI와 이력에 명시한다.
롤백 역시 최신 본문이 적용 직후 결과와 일치하는지 확인하고 제3자의 후속 편집이 있으면 자동 덮어쓰기를 중지한다.
PATCH 응답 유실 때 무조건 재시도하지 않는다. GET으로 적용 여부를 확인하여 중복 작업을 방지한다.
SCHEDULED_HOLD 표시는 실제 예약 취소가 아니다. 자동 발행 방지에는 실제 예약 해제/초안 전환 정책과 권한이 필요하며 현재 코드는 이를 실행하지 않는다.

## Google 감시
HTTP/리다이렉트/canonical/robots/noindex/sitemap 기술 상태와 Search Console 색인 상태를 별도 저장.
공개 검색에 안 보인다는 이유로 미색인이라고 확정하지 않는다. 권한 또는 API 근거 부족 시 확인 불가.
발견됨-미색인/크롤링됨-미색인/soft404 등은 Search Console 근거와 확인시각을 남긴다.
기술적 접근 가능성과 색인됨은 별개다. 상태 변경 글을 우선 표시하며 정상 글에는 유효기간 캐시 적용.

## 개발 순서와 예상 작업량
1. DB/LIVE Sync/Bridge 어댑터: 3~5시간
2. Fast/Deep Recovery: 4~6시간
3. Evidence 기반 신규 생성 엔진 이식: 5~8시간
4. 실제 픽셀 QA/ALT/caption: 3~5시간
5. Google 감시: 2~4시간
6. 통합 UI/무CMD 실행/통합 검증: 3~7시간
합계 20~35시간의 집중 작업 추정. 연결 승인 대기 및 사용자 PC 설치 시간은 별도.
이 시간은 무인 실행이나 마감 약속이 아니다. 대화 작업이 종료된 후에도 개발이 자동 지속된다고 가정하지 않는다.

## 테스트 실행
Python 3.10 이상, 표준 라이브러리만 사용.
폴더에서 `python -m unittest discover -v` 실행.
테스트: 최초 동기화/캐시 재사용/변경 글만 조회/네트워크 실패 보존/목록 제외/충돌 보호/조회 중 변경 감지.
실제 Blogger·Windows·AI 품질·이미지·Google 검증은 다음 단계의 미완료 항목이다.

## 0.2 개발 진행 업데이트
2026-10-09: 읽기 전용 Bridge R3, Python 연결 어댑터, Fast Gate, 세 메뉴 Tk UI 및 데모 실행 추가.
9개 테스트 통과. 형식 검사는 post hash+엔진 버전으로 캐시하고 중복 유사도 인덱스는 별도 테이블 duplicate_checks에 보존한다.
전체 corpus가 변경돼도 모든 글의 형식·AI 검사를 다시 실행하지 않는다. 가벼운 중복 비교만 다시 계산한다.
Bridge 공식 API 문서 확인: fetchBodies=false, 상태별 페이지 조회, ADMIN에서 status 포함.
- https://developers.google.com/blogger/docs/3.0/reference/posts/list
- https://developers.google.com/blogger/docs/3.0/reference/posts/get
- https://developers.google.com/blogger/docs/3.0/reference/posts
초기 상태 설명보다 본 업데이트가 우선한다. 상세 실행법과 미완료 범위는 QUICK_START_KO.md 참조.

## 0.3 개발 진행 업데이트
Evidence-first 생성 파이프라인, Gemini Interactions REST 어댑터, 심층 검사, 단계별 SQLite 체크포인트 및 사용 주제 제외 기록 구현.
기존 글의 근거 조회는 본문 hash+모델+버전 기준 7일 캐시. 텍스트 PASS라도 픽셀 검증 미완료 시 TEXT_PASS_IMAGE_PENDING이며 최종 PASS가 아니다.
생성량은 1~3개로 제한. 최신 LIVE 동기화가 없으면 생성 작업은 보류한다.
완성 본문에 별도 검색 Fact 검사를 수행하고 실제 출처 없는 검색 응답은 보류한다.
검색 도구 출처 annotation 밖의 URL을 장부에 생성하면 보류한다. 출처 등급과 주장 지원 관계는 AI 보조 판정으로, 원문 전문 직접 수집 검증은 아직 미구현이다.
현재 모든 신규 글은 이미지·링크 최종 검증 미구현 때문에 HOLD이며 외부 저장·발행하지 않는다.
18개 자동 테스트 통과. 모의 end-to-end 생성에서 Writer 결과, 독립 Fact 검색, Deep 결과, HOLD 저장 확인.
실제 API 호출, Apps Script 배포, Windows GUI/EXE 검증은 미실시.
주요 남은 작업: 실제 픽셀 QA/ALT/caption, 검증된 링크 연결, Google 상태 감시, 안전 PATCH/롤백, 설정 UI/Windows 패키징.
별도 캐시·작업 테이블: evidence_packs/generation_jobs/generation_events. 핵심 7테이블 유지.
저장된 생성 단계는 재개 구현의 기반이다. 자동 이어쓰기/중단 재개 버튼은 아직 미구현이다.
API 설정은 R3_GEMINI_KEY, R3_GEMINI_MODEL이며 모델은 임의로 자동 변경하지 않는다.
공식 문서 확인:
- https://ai.google.dev/gemini-api/docs/google-search
- https://ai.google.dev/gemini-api/docs/structured-output
중간 개발본을 사용자 설치 대상으로 안내하지 않는다.

## 0.4 개발 진행 업데이트
실제 로컬 이미지 파일 검사와 Gemini 픽셀 입력 구현: 손상/형식/해상도/16:9/파일 크기 검사 → 픽셀 의미·품질 QA → 동일 픽셀로 ALT/caption 작성 → 시각 일치 재확인.
이미지 QA는 파일명이 아닌 픽셀 hash+글 내용 hash+모델+엔진 버전으로 캐시한다. 다른 글의 설명을 재사용하지 않는다.
생성 작업에 이미지 후보 2장 연결과 검사 기록 추가. QA PASS는 이미지 단독 판정이며 글 전체 PASS가 아니다.
실제 API 검증 전이며 모의 검사에 사용한 단색 테스트 이미지의 PASS는 실제 시각 품질 검증 근거가 아니다.
Pillow 의존성 추가. 배포 전 Windows 의존성 설치/패키징 필요.
Google 감시 모듈 및 메뉴 연결: 공개 HTTP/canonical/robots meta/X-Robots-Tag/noindex/redirect와 Search Console 색인 근거를 분리 저장.
Search Console은 R3_GSC_TOKEN/R3_GSC_PROPERTY 설정 시 읽기 전용 URL Inspection 호출. 현재 토큰 자동 갱신/OAuth 화면은 미구현.
robots.txt와 sitemap은 Search Console 관찰 값을 보존한다. 공개 원문 직접 조회·sitemap 포함 여부 검사는 아직 미구현이며 권한 없으면 확인 불가.
정상 색인 글 기본 24시간, 다른 상태 2시간 캐시. 상태 변화/새 문제 우선 표시. 색인 요청 제출 기능 없음.
29개 자동 테스트 통과. 실제 연결/Windows 시각 QA/EXE 미검증. 이미지 생성·공개 업로드·본문 배치·안전 PATCH/롤백·완전 재개는 남은 작업.
공식 문서:
- https://ai.google.dev/gemini-api/docs/image-understanding
- https://developers.google.com/webmaster-tools/v1/urlInspection.index/inspect
- https://developers.google.com/webmaster-tools/v1/urlInspection.index/UrlInspectionResult

## 0.5 개발 진행 업데이트
안전 PATCH 준비/적용 감사 모듈 및 별도 Guarded Bridge 구현. 쓰기는 Script Property R3_ENABLE_WRITES=true에서만 활성화되며 기본 OFF.
기존 읽기 전용 Bridge는 그대로 유지. 두 Bridge 파일을 같은 Apps Script 프로젝트에 동시에 넣지 않는다(doPost 중복).
원본 hash+updated 비교 → Drive 백업 → 원본 재비교 → PATCH → GET 결과 비교.
요청 ID 장부를 side effect 전에 저장. 완료 응답은 동일 요청만 재사용하며 처리 결과 불명 요청은 자동 재시도 금지.
rollback은 backupFileId/블로그/Post ID/백업 폴더 소속 및 현재 expectedHash/updated 검증을 요구한다.
서버 hash와 UTF-8 처리를 Node 테스트로 확인, 서버 측 stale 충돌 및 요청 replay 차단도 모의 검증.
잠금은 Bridge 실행끼리만 보호하므로 Blogger UI 동시 편집의 최종 경쟁 구간은 남아 있다. API 원자적 조건부 PATCH 지원은 확정하지 않았다.
이미지 업로드 어댑터·Bridge 추가, byte hash에 연결된 업로드 receipt로 figure/ALT/caption 배치. 기존 이미지가 있는 본문은 자동 추가하지 않고 별도 교체 계획을 요구한다.
공개 이미지가 리사이즈되어 픽셀이 달라질 수 있으므로 업로드만으로 최종 PASS를 부여하지 않는다. 공개 이미지 GET·재QA는 미구현.
설정 화면과 Windows current-user DPAPI 저장 코드 추가. 비밀값 평문 저장 금지. 다른 OS는 세션 설정만 사용.
Windows DPAPI 실제 실행은 아직 미검증이며 모의 보호 함수로 저장 형식/roundtrip만 검사했다.
36개 Python 자동 테스트와 Node hash/충돌/무재시도 테스트 통과.
UI에 쓰기/업로드 실행 버튼은 아직 연결하지 않았다. 개발 도중 외부 블로그 글은 수정하지 않았다.
남은 핵심 작업: 자동 이미지 생성, 공개 이미지 검증, 내부/외부 링크 검증 및 최종 PASS 통합, 안전 수정 UI, 중단 재개 UI, Windows EXE와 실제 계정 통합 검증.
공식 문서: Blogger posts.patch, Apps Script LockService, Microsoft CryptProtectData/CryptUnprotectData 참조.

## 0.6 개발 진행 업데이트
공개 이미지 GET 후 실제 제공 픽셀을 다시 검사하고 최종 HTML의 ALT/figcaption 일치를 확인하는 경로 추가.
LIVE 내부링크와 근거 장부 A/B 외부링크만 허용. 링크 HTTP 오류, 초안 링크, 내부 링크가 다른 목적지로 redirect, 외부 근거 도메인 변경 시 HOLD.
AI가 현재 LIVE 목록 중 관련 글 1~3개를 선택하는 연결 단계 구현. 없거나 허위 ID를 고르면 HOLD.
최종 PASS는 최신 본문 hash에 연결된 공개 이미지 2장 QA, 최종 독립 Fact 검색, HTML/Fast 검사, 링크 검사, Deep text_verified를 모두 요구한다.
PASS 판정은 파이프라인 내부 판정이며 Google 색인/AdSense 승인을 보증하지 않는다.
PASS 후에도 자동 Blogger 저장/발행 없음. 새 글 저장/예약과 최종 사용자 실행 연결은 아직 남았다.
보류 목록/작업 불러오기/동일 작업 번호 재개/최종 검사 버튼 연결. 유효한 근거 및 같은 근거로 만든 본문을 재사용하고 중복·Fact 검사는 다시 진행한다.
이미지 배치가 저장된 작업은 이어쓰기에서 재생성하지 않고 최종 검사로 이동하도록 안내한다.
이미지 배치가 바뀌면 이전 링크 포함 본문/최종 판정/최종 Fact hash를 무효화한다.
42개 Python 자동 테스트와 Node 보호 테스트 통과. 최종 PASS 테스트는 모의 검증으로 실제 AI 성능 근거가 아니다.
공개 이미지 AI 요청, 실제 Blogger/Google API, Windows GUI/DPAPI/EXE는 아직 실제 환경 검증 전.
남은 주요 기능: 자동 이미지 생성, 이미지 업로드와 수정 UI 연결, 새 글 저장/예약 및 재조회, DB migration 강화, 원문 근거 수집, Windows 실행 패키지와 실계정 검증.

## 0.7 개발 진행 업데이트
설정에서 R3_IMAGE_MODEL을 명시하는 Gemini 이미지 생성 어댑터 구현. 16:9로 요청하고 신규 생성 이미지만 1024×576 JPEG/500KB 이하로 정규화 후 QA.
장면 2개 각각 최초+최대2회 재생성. 시도 로그 영구 저장. 실제 생성 API 호출 검증은 아직 하지 않았다.
PASS-only Publisher: 본문 hash/검사 시각 확인 → 초안 INSERT → GET → 필요 시 publish/publishDate → GET 본문·상태·예약 시각 확인.
이미 저장한 초안은 재사용하며 결과 불명 저장은 자동 재시도하지 않는다. 동일 작업 반복으로 신규 글을 중복 INSERT하지 않는다.
Guarded Bridge에 create_draft/publish_pass 추가. 기본 쓰기 OFF 정책 유지. 미래 예약은 최소 1분 이상의 서버 여유, 클라이언트는 2분 이상 요구.
UI에 이미지 자동 생성/업로드·배치/초안 저장/발행/예약 연결. 외부 작업은 해당 버튼을 눌러야 실행하며 일반 조회에서는 수행하지 않는다.
업로드 전 request ID와 SENDING 기록을 저장해 응답 유실 후 새 request ID로 같은 이미지 중복 업로드를 방지한다.
이미지 후보를 바꾸면 이전 업로드·본문 배치·최종 검사 연결을 무효화한다.
검색설명은 로컬 기록에 보존하지만 Blogger API 저장은 아직 지원 확인 전이며 저장되었다고 주장하지 않는다.
48개 Python 자동 테스트와 Node 보호 테스트 통과. 실계정/Windows/GUI 시각/DPAPI 실행은 검증 전.
현재 남은 주요 작업: 기존 글 수정·롤백 UI, 실제 근거 원문 수집, 최신 corpus 반영 최종 발행 재검사, Google robots/sitemap 공개 원문, DB migration·취소/중단 상태 보강, 사용자에게 적합한 화면 정리, Windows EXE 패키징과 실계정 검증.
Windows EXE를 Linux에서 제작 완료했다고 주장하지 않는다. 이 ZIP은 개발 체크포인트이며 사용자 설치용 완성품이 아니다.
참고 문서:
- https://ai.google.dev/gemini-api/docs/image-generation
- https://developers.google.com/blogger/docs/3.0/reference/posts/insert
- https://developers.google.com/blogger/docs/3.0/reference/posts/publish

## 0.8 개발 진행 업데이트
기존 글 Recovery 수정안 생성/비교/적용 UI 추가. 제목·라벨·이미지 속성 유지, 근거·독립 Fact·Fast/Deep·공개 이미지·링크 검사를 통과한 수정안만 적용 버튼 활성화.
수정안 작성 중 LIVE가 바뀌면 적용 계획을 폐기한다. 적용 전 corpus 변경/검사 1시간 초과도 중지한다.
백업 복원은 적용 직후 hash와 현재 hash가 같아야 하며 제3자 후속 편집이 있으면 중지. 결과 불명 복원은 ROLLBACK_NEEDS_RECONCILE로 표시한다.
최종 발행 준비는 최근 5분 내 성공 동기화 및 검사 당시 corpus hash 일치를 요구한다.
본 작업으로 이미 저장한 초안은 corpus 중복 비교에서 제외하고 원격 본문 자체는 별도 hash 검증한다. 새로 추가된 다른 글은 최종 PASS 재검사를 요구한다.
DB user_version 2 migration 및 이전 DB SQLite backup 구현. 이전 기록을 유지하고 미래 버전 DB는 수정하지 않는다.
작업 중단 토큰/버튼 및 종료 보호 추가. 진행 중 요청은 강제 종료하지 않고 협력적 checkpoint에서 멈춘다. 브라우저나 PC 종료 후 무인 지속 개발을 보장하지 않는다.
TaskLog 테이블과 도우미는 준비되어 있지만 모든 UI 작업의 시작/종료 기록까지 연결한 것은 아니다.
54개 Python 자동 테스트와 Node 보호 테스트 통과. GUI는 코드 연결과 문법 검증 상태이며 실제 화면/Windows 실행 검증 전이다.
남은 작업: 근거 원문 직접 수집, 공개 robots/sitemap 검사, 전체 task 로그 연결, GUI 보기 쉬운 정리와 시각 QA, Windows 빌드·설치 패키지, 실계정 API 통합 검증, Blogger 검색설명 저장 지원 확인.
현재 개발본은 사용자에게 설치를 요구하는 완성본이 아니다. 실제 블로그 글을 수정/발행한 이력 없음.

## 0.9 개발 진행 업데이트
HTML/plain text 근거 원문을 직접 읽어 저장하고, AI가 제시한 연속 근거 구절이 실제 원문에 있는지 검증한다. 독립 출처 2개 및 확인된 사실 4개 이상, 모든 핵심 사실의 지원을 요구하며 실패하면 HOLD. AI가 생성한 원문 검증 도장은 삭제하고 프로그램이 검증 후 기록한다. PDF/로그인 자료는 현재 확인 불가 처리. 출처 신뢰도와 문장의 의미 지원은 AI 판단이 포함되므로 실제 자료로 추가 검증 필요.
새 글 작성/최종 검사 및 기존 글 Recovery에 원문 검증 연결. 원문 변경 hash와 확인 유효기간 검사. Deep 검사 버전 변경으로 이전 판정 재사용 방지.
공개 robots Googlebot 그룹/최장 경로/Allow 우선 규칙 및 sitemap index 순회 구현. 최대 20개 문서, 같은 호스트만 자동 순회하며 부분 조회는 UNKNOWN_OR_PARTIAL. Google 색인 증거와 공개 크롤링 상태를 구분하여 화면 표시. 감시 버전 변경으로 과거 캐시 갱신.
59개 Python 자동 테스트와 Node Bridge 보호 테스트 통과. 외부 응답은 모의 자료이며 실제 Blogger/AI/Search Console 및 Windows GUI/EXE 통합 검증 전. 실제 글 수정이나 발행 수행 없음.
남은 작업: task 로그 전체 연결, 사용자 화면 정리와 실제 시각 QA, Windows 패키징/실행 검증, 실계정 API 검증, 검색설명 저장 지원 확인. 개발 체크포인트이며 설치용 완성품이 아니다.

## 0.10 개발 진행 업데이트
UI 동기화/Google 감시/생성·검사·업로드·발행·수정·복원 worker에 task_runs 시작/완료/오류/사용자 중단 기록 연결. 작업 로그는 오류 클래스만 저장하여 원격 응답과 인증값 저장을 피한다. 종료 기록 없는 RUNNING은 최근 작업 기록 화면에서 종료 미확인으로 표시하며 자동 재실행하거나 완료로 변경하지 않는다. 작업 완료는 발행 성공 또는 품질 PASS를 뜻하지 않으며 글별 검사 상태는 별도 관리한다.
상단 작업 기록 버튼 추가. 최근 50개 기록 열람. 새 글 작업 결과는 전체 JSON 대신 작업 번호/단계/상태/보류 이유만 표시하며 내부 payload·근거 원문·검사 응답 전체를 화면에 쏟아내지 않는다.
생성/이미지 후보/최종 검사 중 사용자 중단은 HOLD 저장 후 Cancelled를 상위 worker에 전달하여 중단을 작업 완료로 기록하지 않는다. 저장 요청 중에는 결과 확인 보호를 유지한다.
64개 Python 자동 테스트 및 Node 보호 테스트 통과. 실제 UI worker의 데모 동기화 완료/중단 기록, 생성 중단 전파와 HOLD 저장, 민감한 오류 문자열 로그 제외를 검사했다. Tk 화면 렌더링/Windows/실계정 API 검증은 미완료.
남은 작업: Windows 패키징·설치·실행 검증, 전체 화면 시각 QA, 실계정 API 연결 검증, 검색설명 저장 지원 확인. 이 파일은 개발 보관본으로 아직 사용자 설치용 완성본이 아니다.

## 0.11 개발 진행 업데이트
일반 실행/진단 실행을 공통 startup으로 통합. 오류 기록은 종류·파일명·함수·행만 저장하며 인증값·원격 응답·소스 행·예외 메시지·환경변수는 제외한다. 오류 기록 1MB 초과 시 이전 파일 하나로 회전. Tk 초기화 자체 실패도 기록 후 처리한다.
사용자 데이터 폴더에 단일 실행 잠금 추가. Windows msvcrt 및 POSIX flock 구현. 현재 POSIX에서 중복 실행 차단/잠금 해제 테스트; 실제 Windows msvcrt 경로는 실행 전이다.
Windows 전용 빌드 스크립트: Python/Node 테스트 후 PyInstaller 일반(windowed)·진단(console) 각각 onedir 빌드. 의존성 자동 설치나 실계정 호출 없음. 두 빌드 출력과 명시적 문서만 개발 배포 ZIP에 복사하고 SHA256 manifest 상태 WINDOWS_BUILD_UNVERIFIED 기록. Linux 실행 시 Windows 빌드를 명시적으로 중지한다.
PyInstaller 6.22.3 빌드 의존성 지정은 공식 문서 기준이며 이 환경에서 설치하거나 Windows EXE를 생성하지 않았다. 사용자는 아직 개발 환경 설치/다운로드를 할 필요가 없다.
WINDOWS_VALIDATION.md에 실제 Windows 확인 항목과 미실시 상태 기록. 오래된 QUICK_START_KO.md를 현재 구현과 미검증 범위에 맞춰 다시 작성.
70개 Python 자동 테스트, Node 보호 테스트 통과. 빌드 명령 구성·배포 대상 제한은 모의 출력 검사이며 실제 EXE 시험이 아니다. 실제 GUI/DPI/Windows DPAPI/실계정 API/검색설명 저장 지원은 남아 있다.
공식 참고: https://pyinstaller.org/en/stable/usage.html

## 0.12 마무리 안정성 점검
최종 corpus hash에 제목 포함. 본문이 같아도 다른 글의 제목 변경 시 최종 생성/수정 검사 결과를 재사용하지 않는다. 미래 시각의 동기화 기록은 최신 동기화로 인정하지 않는다. 기존 개발본의 corpus hash는 불일치로 재검사를 요구한다.
서버 request_status 조회 추가: 인증 후 기존 Drive journal만 읽으며 폴더 생성/새 저장/재발행을 수행하지 않는다. 서버 DONE 기록의 작업 종류·블로그 ID·글 ID 및 실제 GET 제목/본문/라벨/상태/예약 시각이 원래 계획과 일치할 때 publish_history를 VERIFIED로 회복한다. RUNNING/NOT_FOUND/불일치는 보류 유지.
화면에 이전 저장 결과 재확인 버튼 연결. 실제 Blogger 저장은 되었으나 응답이 끊긴 경우 중복 초안을 만들지 않고 확인 가능. 서버 작업 자체가 미확정인 경우 자동 복구/재시도하지 않는다. 현재 추가 기능은 생성 글 저장/발행 이력용이며 수정·이미지 업로드 불명 요청의 자동 복구는 포함하지 않는다.
목록 조회/저장/발행/업로드/수정 적용/롤백/저장 결과 확인에서 불필요한 Gemini 모델·키 요구 제거. AI가 필요한 작업에서만 Gemini를 초기화한다. Blogger 동기화는 실제 작업 전에 유지한다.
74개 Python 자동 테스트와 Node UTF8/hash/충돌/no-replay/읽기 전용 요청 확인 테스트 통과. 서버 응답은 모의 자료이며 실계정 런타임 검증 전. Windows EXE/시각 QA/실계정 통합/검색설명 저장 확인은 남아 있다.

## 0.13 결과 불명 작업 보호 확장
수정 GET 응답 분실 후 서버 DONE·backup ID·현재 본문/라벨/상태/URL/hash가 일치하면 기존 수정 기록을 VERIFIED로 확인. 일치하는 수정안도 APPLIED로 표시한다. 재PATCH하지 않으며 이후 편집이 감지되면 보류. 작업 기록 창에 수정 확인 번호와 생성 저장 확인 번호를 표시한다.
이미지 업로드 journal에 원본 byte_hash 추가. 서버 DONE 및 로컬 검사 파일/요청/서버 hash가 일치할 때만 업로드 영수증을 복구. URL 검사 후 저장하며 public_pixel_verified는 false로 유지해 최종 공개 픽셀 검사를 생략하지 않는다. 재업로드 요청을 하지 않는다. 이전 Bridge 기록에 byte_hash가 없으면 자동 수용하지 않는다.
수정 결과 확인/이미지 업로드 결과 확인 버튼 추가. 이 확인 작업은 Gemini를 요구하지 않는다. 최신 guarded Bridge 배포가 필요하며 아직 실계정 검증 전.
백업 복원 후 GET 실패·본문 불일치도 ROLLBACK_NEEDS_RECONCILE로 기록하도록 보호 범위 확장. 복원 결과 불명 상태는 자동 재복원하지 않는다. 복원 journal을 통한 자동 확인은 아직 구현하지 않았다.
79개 Python 자동 테스트 및 Node Bridge 보호/조회 테스트 통과. API는 모의 응답, GUI는 문법/코드 연결 검사이며 Windows 화면/실계정 검증은 아직 남아 있다. 설치용 최종판이 아니다.

## 0.14 복원 결과 확인
복원 요청 번호를 요청 전에 SQLite에 저장. 응답 분실 시 서버 DONE rollback 기록과 현재 GET 본문/제목/라벨/상태/URL/hash가 원래 백업과 일치해야 ROLLED_BACK으로 확인한다. 재복원 호출은 하지 않으며 이후 편집/미확정/과거 요청 번호 없는 기록은 확인을 보류한다. 화면의 수정·복원 결과 확인 버튼에서 기록 상태에 따라 경로를 선택한다.
81개 Python 자동 테스트 통과. 응답 분실 뒤 조회만으로 복원 확인, 이후 편집 확인 중지 테스트 추가. 실계정과 Windows 실행 검증 전이다.
20~35시간은 전체 작업량 추정이며 응답 종료 후 자동 무인 개발을 보장하지 않는다.

## 0.15 연결 준비 안내
연결 준비 상태 화면 추가. API 호출 없이 입력 존재/형식을 검사하며 실제 인증·모델 권한 확인 완료로 표시하지 않는다. 비밀값은 표시하지 않는다. AI 작업은 필요한 설정만 실행 전에 요구한다. 잘못된 Bridge 개발용 /dev 주소를 차단하고 배포 /exec 주소를 요구한다.
설정 파일 최상위가 목록 등 잘못된 형식일 때 통제된 설정 오류 처리.
85개 Python 자동 테스트 통과. 실제 Windows·API 연결은 아직 미검증.

## 0.16 설정 오류 경계 점검
설정 안내와 Bridge 실제 주소 검증을 같은 함수로 통합. 잘못된 배포 경로·사용자 정보 포함 URL·query 인증값·malformed URL 차단. 동기화/Google 감시에도 사전 설정 검사와 Google 시작 전 중단 checkpoint 연결.
잘못된 설정 JSON 형태·암호화 envelope·파일 접근 오류를 SettingsError로 처리하여 설정을 다시 입력하도록 안내.
88개 Python 자동 테스트 통과. 실제 API/Windows 검증은 남아 있다.

## 0.17 Google 감시 캐시·문제 표시
Blogger content_hash를 감시 캐시에 연결해 변경된 글은 감시 결과를 재조회. monitor 버전 변경으로 과거 결과 재사용 방지. robots BLOCKED/기타 현재 문제/Console 오류는 needs_attention 표시하고 문제 글을 상태 변화 유무와 관계없이 위로 정렬.
404/서버 오류가 canonical 경고에 덮이지 않도록 canonical_review 별도 필드. robots 지시문 정확한 토큰으로 noindex/none 판정. 변화 항목 목록 기록. Google 색인 스냅샷의 세부 변경도 비교.
91개 Python 자동 테스트 통과. 실제 API/Windows 실행 검증 미완료.
공식 참고 https://developers.google.com/search/docs/crawling-indexing/robots-meta-tag

## 0.18 지시문·근거 추출 정확도
max-image-preview:none을 noindex로 오인하지 않도록 robots 지시문 이름과 값을 구분. 다른 검색봇 대상 X-Robots-Tag는 Googlebot 규칙으로 오인하지 않는다. 감시 버전 갱신.
근거 원문에서 strong/span 같은 인라인 태그가 단어를 끊지 않도록 본문 추출 개선. 블록 사이만 공백 추가하며 HTML fragment도 추출한다. 추출 버전 및 evidence cache 버전 변경으로 이전 캐시 갱신.
93개 Python 자동 테스트 통과. 실계정 API/Windows 검증은 미완료.

## 0.19 최종 판정·유효기간 보호
심층 점수와 모든 항목 PASS여도 review issues가 남으면 text_verified false. 비객체 응답은 검사 보류. Deep cache 조회 시 원문 확인 유효성을 재검사하며 검사 버전 갱신.
공통 freshness 검사 도입: 누락/손상/시간대 없는 시각/미래 시각/만료 시각은 재검사 요구. 발행 직전 동기화와 최종 검사 및 근거 확인 시각에 적용.
96개 Python 자동 테스트 통과. 실제 계정·Windows·GUI 검증 전이며 설치용 완성본은 아니다.

## 0.20 原문 검사 기록 재검증
원문 확인 시각/pack hash만으로 검사 완료를 인정하지 않는다. 저장된 원문 text_hash·인용 구절 존재·주장/출처 연결·독립 호스트·최소 4개 사실·모든 핵심 사실 지원을 재검사. 불완전한 과거 기록은 재확인 요구. 인용 지원의 의미 판단은 여전히 AI 검토에 포함되며 단순 문자열 일치만으로 정확성을 보장하지 않는다.
긴 원문은 실제 저장된 50000자 hash와 전체 추출본 hash를 구분하여 저장. 추출/근거/Deep 버전 갱신.
99개 Python 자동 테스트 통과. 원문 변경·인용 누락·허위 구절의 캐시 수용 차단을 확인. 실계정/Windows 검증은 미완료.

## 0.21 최종 검사와 발행 조건 일치
최종 PASS 기록에 gate version·evidence hash·라벨/검색설명 hash 저장. 발행 준비 시 동일 기준 version, 근거 원문 기록 유효성 및 변경 여부를 확인한다. 본문이 같아도 근거·라벨·검색설명 변경 또는 과거 검사 version이면 재검사 요구. 검색설명 hash 확인은 로컬 무결성 검사이며 Blogger 검색설명 실제 저장 지원을 의미하지 않는다.
101개 Python 자동 테스트 통과. 실제 API/Windows 실행 검증 미완료.

## 0.22 기존·예약 글 전체 심층 검사 연결
선택 글 심층 검사 경로에 최신 GET baseline, 기본 중복/형식, 독립 Fact 검색, 근거 Deep, 공개 이미지 픽셀/ALT/caption, 공개 링크 검사를 통합. 모든 단계 통과 시 LIVE PASS 또는 SCHEDULED_PASS. 이미지/링크 불합격 예약은 SCHEDULED_HOLD, LIVE는 B. 검사 종료 GET에서 LIVE가 바뀌면 판정 저장 중지.
검사 결과의 등급·지적 사항을 화면에 표시하고 선택 글 목록 등급을 갱신. 전체 검증 완료와 미완료 안내 구분. 이 경로는 선택한 글만 처리하며 전체 글에 AI 호출을 강제하지 않는다.
103개 Python 자동 테스트 통과. 새 경로의 예약 PASS/HOLD 테스트는 이미지·링크 모의 응답이며 실제 API/Windows 화면 검증 전이다. 기존 오래된 caption HTML은 엄격한 연결 검사로 보류될 수 있어 실제 글 검증 후 보완 필요.

## 0.23 기존 전체 검사 재사용 보호
전체 검사 결과에 검사 당시 corpus hash 기록. Fast 검사 시 동일 본문·동일 corpus·최신 엔진·유효기간의 전체 판정 유지. 다른 글 추가/변경 또는 LIVE 24시간·예약 2시간 만료 시 NEEDS_DEEP/SCHEDULED_HOLD로 전환하며 자동 AI 전체 재검사는 하지 않는다. 과거 전체 검사 버전도 재검사 요구.
판정 저장 직전 로컬 content_hash/updated/present도 확인해 검사 중 동기화 변경을 차단. 화면에서 무효가 된 과거 verified 표시를 제거하고 재검사 사유 표시.
103개 Python 자동 테스트 통과. 기존 예약 PASS의 Fast 검사 유지 및 corpus 변경 HOLD 전환을 추가 검증. 실제 API/Windows 화면 검증 미완료.

## 0.24 진행 표시·중복 계산 감소
전체 corpus hash를 Fast 실행당 한 번 계산하도록 개선하여 글마다 전체 본문 지문을 반복 계산하지 않는다.
하단 공통 상태 표시를 세 메뉴에서 공유. 조회/변경/본문 재사용/검사 재사용 수 및 실제 PASS/A/B/C/예약 결과/누락/검증 미완료 수 표시. 생성 작업 결과의 번호를 입력칸에 자동 반영.
104개 Python 자동 테스트 통과. Tk 문법/연결 검사 상태이며 실제 화면 배치/Windows DPI 검증은 아직 미완료. 실제 API 연결도 검증 전이다.

## 0.25 오프라인 작업 기록 조회
보류 목록/작업 불러오기는 계정 설정·Bridge·AI 초기화·LIVE sync 없이 저장 DB만 조회. 데모 모드에서도 실제 보관된 생성 기록 조회는 가능하며 API 쓰기는 수행하지 않는다. 최신 LIVE 상태 미확인임을 표시한다. 재개/최종 검사/발행은 기존 최신 동기화 보호를 유지한다.
106개 Python 자동 테스트 통과. 실제 UI worker에서 Bridge·Gemini 초기화 금지 mock을 걸고 로컬 작업 불러오기 경로 검증. 실제 Windows/실계정 API 검증 미완료.

## 0.26 일일 SQLite 백업
실행 잠금 획득 후 실제/데모 DB를 SQLite backup API로 일일 snapshot. 원본 읽기 전용 연결, 백업 quick_check, 임시 파일→완료 파일 원자 전환. 원본 DB 없는 경우 새 DB를 만들지 않는다. DB별 최신 7개 일일 snapshot 유지. 설정·인증값 파일은 복사하지 않는다. 백업 검증 실패 시 원본을 변경하지 않고 시작 오류 기록을 남긴다.
109개 Python 자동 테스트 통과. 백업 시점 기록 보존, 같은 날 중복 생성 방지, 보관 수 검증. 복원 UI는 아직 준비 전이며 자동 원본 덮어쓰기를 하지 않는다. 실제 Windows/실계정 검증 미완료.

## 0.27 백업 내용 확인
백업 확인 화면에서 파일명·무결성·글/버전/검사/생성/실행 기록 수를 읽기 전용 조회. 손상 파일은 확인 실패 표시. 자동 복원·원본 덮어쓰기 없음. 백업 조회와 생성의 SQLite 연결을 명시적으로 닫도록 보강.
110개 Python 자동 테스트 통과. 실제 Windows GUI/실계정 API는 검증 전.

## 0.28 화면 읽기 편의
상단 제목과 버튼 도구 행 분리. 글 목록 세로 스크롤, 긴 결과·작업 기록·백업·비교창 텍스트 스크롤 추가. Google 결과는 쉬운 접근 상태·HTTP 응답·이동 주소·대표 주소·robots·sitemap·색인·캐시 재사용 여부 표시.
111개 Python 자동 테스트 및 문법 검사 통과. 실제 Tk 화면 크기/DPI 검증은 아직 미실시이며 최종 UI 합격을 주장하지 않는다. 실계정 API도 검증 전.

## 0.29 저장 계획 변경·현재 결과 확인
검토한 저장 계획 전체 지문 추가. 실행 직전 mode/시간/본문/라벨/요청 번호 등 변경 시 새 계획 검토 요구. 초안 계획을 발행 계획으로 변경해 재사용하는 경우 저장 요청 전에 차단.
이미 VERIFIED인 기록도 결과 확인 버튼에서 실제 GET을 수행하며 현재 본문/상태/URL/예약 시각 변경 시 재확인 요구. 잘못된 블로그 연결 검사는 기록 반환 전에 수행.
114개 Python 자동 테스트 통과. 모의 통합 저장에서 계획 mode 변경·잘못된 블로그·이후 본문 편집 차단 검사. 실제 계정/Windows 실행 검증 미완료.

## 0.30 저장 계획 확인 UI
초안/발행/예약 버튼은 최신 동기화 후 계획만 준비하여 제목·본문 텍스트·라벨·블로그 ID·UTC 예약 시각·로컬 검색설명 확인창을 연다. 이 단계에서는 저장 요청 없음. 확인창의 실행 버튼에서 동일 지문 계획으로 최신 동기화와 최종 조건 재검증 후 실행한다. 취소/창 닫기는 저장하지 않는다. 본문 텍스트 확인이며 HTML/이미지 렌더링 미리보기는 아직 아니다.
115개 Python 자동 테스트 통과. 실제 UI worker의 preview 단계에서 insert/publish 요청 없음 확인. 실제 GUI/Windows/API 검증은 미완료.

## 0.31 제목 보완 경로
제목 누락·길이/HTML/줄바꿈 오류·동일/높은 기본 유사 제목은 최대 3회 보완. 기존 Blogger 및 과거 생성 작업 제목을 비교하며 시도·사유를 작업 payload/이벤트에 기록. 유효한 재개 제목은 재생성하지 않는다. 제목 변경 시 종전 근거·Writer 본문·검색설명·Deep·최종 결과 무효화. 제목 단계의 의미 유사성은 기본 비교와 AI 생성 지시에 의존하며 본문/주제 의미 중복 검사는 기존 별도 경로 유지.
근거 재개 유효기간도 공통 freshness 사용하여 미래/손상 시각은 재조사.
117개 Python 자동 테스트 통과. 실제 API/Windows 검증 미완료.

## 0.32 Research Recovery 응답 보호
출처 URL/ID/등급·사실 분류/내용 타입 검증 강화. 손상 URL은 통제된 HOLD. 근거 장부 형식만 잘못되면 검색 결과를 재사용해 형식 보완; 근거 부족은 추가 검색. 최대 3회 기록/사유 보관. 실제 검색 없는 응답·검색 밖 출처는 계속 중지. 실패 trace는 생성 payload에 보존.
119개 Python 자동 테스트 통과. 형식 오류 3회 동안 검색 1회만 수행하고 실패 원인을 보존하는 모의 경로 검사. 실제 API/Windows 검증 미완료.

## 0.33 시작 시 첫 조회
UI 준비 후 첫 동기화/Fast 검사를 자동 시작. 기본 DEMO이며 연결 설정에서 시작 모드 LIVE를 명시 선택해 저장해야 실제 Blogger 자동 조회. 알 수 없는 시작 모드는 DEMO로 처리. 시작 모드 선택은 조회만 제어하며 생성·수정·발행을 자동 실행하지 않는다. 로컬 기록을 Blogger 조회 대신 원본으로 사용하지 않는다.
정식 Python package __init__ 및 개발 버전 지정.
121개 Python 자동 테스트 통과. 시작 모드 저장/안전 기본값 검증. 실제 GUI 자동 시작/Windows/실계정 조회 검증은 남아 있다.

## 0.34 공식 AI 응답 계약 점검
Google Interactions 공식 structured/image response_format 및 model_output/url_citation 형식을 대조. 텍스트/이미지의 공통 response parser 도입. 상태가 incomplete/in_progress/failed/cancelled/requires_action이면 부분 결과를 수용하지 않는다. 잘못된 응답 단계/본문 형식은 AIError로 통제. 상태 없는 과거/mock outputs 형식은 호환 경로로 유지하므로 실제 API 계약 검증은 별도 필요.
124개 Python 자동 테스트 통과. 실 API 호출 없음. Windows/실계정 검증 미완료.
공식 참고 https://ai.google.dev/api/interactions-api-v1 및 https://ai.google.dev/gemini-api/docs/interactions-breaking-changes-may-2026

## 0.35 미완료 재검사 상태
기존 글 심층 검사 중 오류/중단 시 최신 incomplete 검사 기록 추가. 이전 이력은 보존하고 현재 LIVE NEEDS_DEEP/예약 SCHEDULED_HOLD로 표시. 이후 Fast에서 과거 PASS를 복원하지 않는다. UI 오류 표시 전 목록 판정 갱신. 현재 글이 존재하고 블로그 범위를 확인한 경우에만 기록한다.
125개 Python 자동 테스트 통과. 실제 Windows 화면/실계정 API 검증은 미완료.

## 0.36 Search Console 오류 격리
Search Console nested 응답과 상태 타입을 검증하고 손상/누락은 ValueError로 처리. Monitor는 공개 HTTP 결과를 유지하며 색인 확인 불가/주의 필요로 기록. 인증 토큰은 결과에 포함하지 않는다. Console HTTP 응답 크기 상한을 초과 여부까지 검사. 공개 HTML의 알 수 없는 charset은 UTF8 대체 디코딩.
127개 Python 자동 테스트 통과. 실제 Windows/API 연결 검증 미완료.

## 0.37 LIVE metadata 변경 감지
수정 시각과 상태가 같아도 목록에 제공된 제목 또는 URL이 DB와 다르면 해당 글만 상세 조회한다. 해당 필드가 없는 기존 adapter는 기존 비교를 유지한다. 상세 조회 결과의 제목/URL이 목록과 달라졌다면 전체 동기화를 중지하고 이전 글·버전 기록을 보존한다. 다음 실행에서 최신 목록을 다시 읽어야 한다.
129개 Python 자동 테스트 및 Bridge hash/conflict/replay/read-only reconciliation 테스트 통과. 실제 Windows/API 연결 검증 미완료.

## 0.38 기존 이미지 설명 연결
기준 Auto Blog Studio의 separator 이미지 div + 바로 뒤 abs-v23-caption div 형식과 figure/figcaption을 함께 지원. 설명은 각 이미지의 HTML 구조에 따라 연결하며 전역 순서로 다른 이미지의 설명을 대체하지 않는다. 이미지 다수/설명 중복/누락/빈 설명/중간 본문이 있는 불확실한 연결은 HOLD. 본문을 자동 변경하지 않으며 실제 픽셀 QA와 최종 ALT/설명 의미 일치 검사는 유지. 임의 span 등 식별 근거가 없는 형식은 보류 유지.
132개 Python 자동 테스트 통과. 실제 Windows/API 연결 검증 미완료.

## 0.39 이미지 AI 실패 기록
이미지 관찰/ALT 생성/일치 확인 단계의 AIError는 HOLD 이력으로 보존하고 PASS 캐시에 저장하지 않는다. 예외의 원격 응답 내용은 저장하지 않는다. 배열/문자열 등 잘못된 일치 확인 형식도 HOLD. 공개 이미지 최종 확인의 AIError 역시 통제된 ImageHold로 처리. 이미지 QA 캐시 버전을 갱신해 종전 결과를 새 규칙으로 재검사한다.
134개 Python 자동 테스트 통과. 실제 Windows/API 연결 검증 미완료.

## 0.40 공개 이미지 통합 경로 검증
이미지가 없거나 어떤 이미지의 ALT라도 비어 있으면 다운로드/AI 호출 전 HOLD. 기존 separator/abs-v23-caption과 figure/figcaption이 혼합된 본문을 모의 픽셀 다운로드 → QA → 본문 ALT/설명 확인까지 연결 검증. 최종 확인의 AIError/잘못된 형식/불일치 모두 PASS 반환 차단. 실제 이미지 다운로드나 실 AI 호출은 수행하지 않은 모의 통합 검사다.
137개 Python 자동 테스트 통과. 실제 Windows/API 연결 검증 미완료.

## 0.41 Google 문제 변화 표시
문제 코드를 이전 검사와 비교하여 새 문제/지속 문제/해소된 문제를 기록. 첫 검사 여부 별도 표시. 화면 정렬은 새 문제 → 상태 변화 → 기존 주의 항목 → 정상. 종전 캐시 버전은 새 규칙으로 갱신. 공개 관찰과 Search Console 확인은 계속 분리하며 해소 표시가 색인 승인 등을 뜻하지 않는다.
139개 Python 모의 자동 테스트 통과. 실제 Windows/API 연결 검증 미완료.

## 0.42 Google 캐시 손상 복구
Google 기록 JSON/필수 필드/문제 목록 타입 검증. 손상 기록은 재조회하며 이전 비교 불가 표시, 거짓 변경/해소 표시 차단. 날짜는 공통 freshness 검사로 timezone 누락/미래/손상 날짜 재조회. robots/sitemap 문서 캐시도 날짜 및 JSON/상태/본문 검증 후 재사용. 정상 캐시 TTL과 changed-only 동작 유지.
141개 Python 모의 자동 테스트 통과. 실제 Windows/API 연결 검증 미완료.

## 0.43 발행 이력 손상 차단
저장 이력 JSON/object/계획 필수 값/라벨/plan hash/완료 post ID와 상태 검증. 손상 VERIFIED 이력은 own-post 제외 계산 및 발행 계획 준비에서 PublishHold. 재조회 reconcile도 서버 접근 전 손상 계획을 차단. 손상된 완료 기록을 신규 글 생성의 근거로 사용하지 않는다.
143개 Python 모의 자동 테스트 통과. 실제 Windows/API 연결 검증 미완료.

## 0.44 수정/롤백 기록 대상 검증
공통 수정 계획 검증: 블로그/글 ID/원본 hash/updated/URL/제안 필드와 라벨 타입 일치. 손상 JSON 또는 다른 대상의 기록은 수정 확인·롤백·롤백 확인에서 원격 접근 전 중지. 수정안 PASS 적용은 공통 freshness와 payload/대상 검증 후 진행. 기존 기록 상태를 유지하고 잘못된 기록으로 신규 적용 이력을 만들지 않는다.
145개 Python 모의 자동 테스트 통과. 실제 Windows/API 연결 검증 미완료.

## 0.45 관련 수정안 오류 격리
수정 결과 reconcile에서 관련 제안은 동일 블로그/글만 조회하고 계획 유효성·요청 ID·제안 내용 일치 시 APPLIED. 손상 제안은 그대로 보존하며 확인된 apply audit의 VERIFIED 전환을 방해하지 않는다. 읽지 못한 관련 기록 수를 반환하고 UI 결과에 안내. 원격 PATCH 재호출 없음.
146개 Python 모의 자동 테스트 통과. 실제 Windows/API 연결 검증 미완료.

## 0.46 예약 시각 응답 보호
예약 비교 공통 함수: 문자열/명시 시간대 검증 후 UTC로 비교. 원격 published 누락/손상/시간대 없음은 통제된 PublishHold. 실행 후 불확실 결과는 NEEDS_RECONCILE 유지하며 반복 실행 시 추가 초안 생성/예약 호출 차단. 한국 시간과 UTC 동일 시각 및 시각 불일치 모의 검사.
148개 Python 모의 자동 테스트 통과. 실제 Windows/API 연결 검증 미완료.

## 0.47 실행 계획 필수 정보 보호
실행 전 및 이력 조회 공통 발행 계획 검증. 작업 번호는 양의 정수(bool 제외), 본문 hash/검사 시각/라벨/요청 ID/예약 방식 검증. 누락 또는 형식 오류 계획은 원격 GET/쓰기 및 새 발행 audit 생성 전 PublishHold. 재계산한 plan hash가 있어도 잘못된 필드나 본문 hash를 통과시키지 않는다.
149개 Python 모의 자동 테스트 및 Bridge hash/conflict/no replay/read-only reconcile 테스트 통과. 실제 Windows/API 연결 검증 미완료.

## 0.48 생성 PASS 기록 형식 보호
load_job은 손상 JSON/비객체 payload를 통제된 ValueError로 안내. 발행 준비는 작업 조회 오류를 PublishHold로 변환하고 final 객체/비어 있지 않은 제목·본문·검색설명/검색설명 길이/라벨 형식을 검증. 표시상 PASS인 손상 기록도 저장 계획 생성 차단. 원본 기록 상태/내용은 자동 변경하지 않는다.
151개 Python 모의 자동 테스트 통과. 실제 Windows/API 연결 검증 미완료.

## 0.49 URL 변경 적용 전 차단
Apply는 hash/updated가 같아도 현재 URL이 계획과 다르면 audit/원격 PATCH 전 중지. Guarded Bridge는 백업 후 재조회에서 최초 조회 대비 URL도 비교하여 백업 중 주소 변경을 PATCH 전에 차단. 기존 hash/updated 및 저장 후 URL 검증 유지.
152개 Python 모의 자동 테스트 및 Bridge hash/conflict/no replay/read-only reconcile/백업 중 URL 변경 PATCH 0회 테스트 통과. 실제 Windows/API 연결 검증 미완료.

## 0.50 수정 계획 변경 확인
Apply.prepare에서 전체 계획 digest를 저장하고 실행/이력 검증 시 비교. 검토 후 제목·본문·라벨이 바뀌면 원격 GET 및 PATCH 전 중지. 롤백 요청 번호는 최초 수정 검토 후 생성되는 운영 기록으로 digest 비교에서 제외하며 원본 수정 계획 hash는 유지. 종전 plan_hash 없는 개발 이력은 자동 수용하지 않고 새 검토 필요. 이는 변경 탐지 checksum이며 서명/인증 기능이 아니다.
153개 Python 모의 자동 테스트 통과. 실제 Windows/API 연결 검증 미완료.

## 0.51 AI 필요 작업 정책 통일
UI AI 초기화와 설정 검사에서 동일 AI_ACTIONS 사용. 저장 결과 확인/수정 적용/복원/Google 조회 등 비AI 작업은 AI 키·모델 없이 Blogger 설정으로 진행. 로컬 목록/작업 조회는 설정 검사에서도 연결정보 불필요. 모든 알려진 작업의 설정 요구를 모의 검사. 기존 worker는 이미 비AI 작업에서 AI를 호출하지 않았으며 이번 변경은 정책 중복 제거와 로컬 설정 검사 일치 보강이다.
155개 Python 모의 자동 테스트 통과. 실제 Windows/API 연결 검증 미완료.

## 0.52 완성판 준비 점검
release_check.py 기본 데모/명시적 --live 읽기 전용 개발자 점검 도구 추가. 임시 DB로 첫/두 번째 동기화와 Fast 등급 집계, 인증값/본문 출력 없음. 데모 실제 실행: 첫 3개 변경, 두 번째 3개 재사용. RELEASE_STATUS_KO.md 및 Windows 실계정 점검 절차 추가. 실계정/Windows 시험은 미실시.
156개 Python 모의 자동 테스트 통과.

## 0.53 Windows 묶음 사전 검사
실행 EXE 누락/빈 파일, 사용자 설정·DB·백업·로그·환경 파일, 외부 symlink, 비어 있지 않은 배포 대상, 안내 문서 누락을 복사 전 차단. 테스트 파일의 mock-exe는 실제 실행 파일이 아니며 실제 Windows 빌드 검증을 뜻하지 않는다.
157개 Python 모의 자동 테스트 통과. 실제 Windows/API 연결 검증 미완료.

## 0.54 배포 파일 무결성 검사
verify_release.py는 manifest 필수 파일/경로/누락/추가/sha256 변경을 검사하며 EXE 실행/계정 접근 없음. build_windows.bundle이 ZIP 생성 전 자동 검사. 무결성 PASS와 Windows/API 실행 검증을 별도 필드로 표시. checksum은 진위 인증 서명이 아니다.
159개 Python 모의 자동 테스트 통과. 실제 Windows/API 연결 검증 미완료.

## 0.55 검사 캐시 손상 격리
Fast 캐시 JSON/dataclass/등급/route/issues/metrics/verified 형식 검증. 손상 글만 재검사하며 정상 캐시 재사용 유지. 손상 또는 비객체 Deep 기록은 유효 PASS로 재사용하지 않고 재검사 필요 판정. 손상 이력은 삭제하지 않는다.
161개 Python 모의 자동 테스트 통과. 실제 Windows/API 연결 검증 미완료.

## 0.56 목록 등급과 캐시 일치
Fast 결과 재사용 시 posts 등급/최종 검사일도 해당 기록으로 갱신. 유효 Deep 결과는 이후 보존하며 상태별 허용 등급을 확인. EMPTY anomaly는 Deep 기록으로 덮어쓰지 않는다. 근거 없는 posts PASS를 넣은 모의 시험에서 최신 캐시 판정으로 복구.
162개 Python 모의 자동 테스트 통과. 실제 Windows/API 연결 검증 미완료.

## 0.57 실환경 전환 준비 점검
build_preflight.py는 Windows/Python3.12/Tk/Pillow/PyInstaller/Node 존재를 오프라인 확인하고 빌드 진입 전에 부족 조건을 안내. 자동 설치/실계정 접근 없음. 현재 환경 실제 점검: Linux, PyInstaller 없음, R3 연결 환경변수 모두 없음. 따라서 Windows/실계정 시험 진행 불가.
164개 Python 모의 자동 테스트 통과.

## 0.58 Windows 원격 빌드 설정
수동 workflow_dispatch Windows GitHub Actions 구성. 저장소 최상위에 R3_0 내용을 배치하는 구조. contents read/persist-credentials false, 계정 키 없이 모의 테스트/빌드/무결성 검사 후 UNVERIFIED 개발 ZIP 보관. CLOUD_BUILD_KO.md에 미실행 및 저장소 연결 필요 명시. 공식 actions checkout/setup-python/upload-artifact 문서를 확인했으나 원격 실행은 미실시.
164개 Python 모의 자동 테스트 통과. 실제 Windows/API 연결 검증 미완료.
