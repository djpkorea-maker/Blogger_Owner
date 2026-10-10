"""Local configuration checks only; presence never implies API authentication."""
import re
from urllib.parse import urlparse

LABELS={'R3_BLOG_ID':'Blogger 블로그 ID','R3_BRIDGE_URL':'Bridge 웹 앱 주소','R3_BRIDGE_SECRET':'Bridge 인증값','R3_GEMINI_KEY':'Gemini API 키','R3_GEMINI_MODEL':'글 검사 모델명','R3_IMAGE_MODEL':'이미지 생성 모델명','R3_GSC_TOKEN':'Search Console 접근 토큰','R3_GSC_PROPERTY':'Search Console 속성 주소'}
AI_ACTIONS={'replace_post','replace_all','replace_resume','repair_image_import','repair_image_generate','repair_alt','repair_validate','deep','generate','images','repair','resume','finalize','generate_images'}
LOCAL_ACTIONS={'jobs','load_job'}
KNOWN_ACTIONS=AI_ACTIONS|LOCAL_ACTIONS|{'repair_image_choose','repair_image_cancel','sync','google','apply_repair','rollback','reconcile_apply','reconcile','reconcile_images','upload_images','draft','publish','schedule','execute_plan'}

def bridge_url_valid(value):
    try:
        parsed=urlparse(value)
        return parsed.scheme=='https' and parsed.hostname=='script.google.com' and parsed.netloc=='script.google.com' and bool(re.fullmatch(r'/macros/s/[A-Za-z0-9_-]+/exec',parsed.path)) and not parsed.query and not parsed.fragment
    except (ValueError,TypeError):return False

def problems(values):
    issues={}
    for key,label in LABELS.items():
        value=values.get(key,'')
        if not isinstance(value,str) or not value.strip():issues[key]=label+' 미입력';continue
        value=value.strip()
        if key=='R3_BLOG_ID' and not (value.isascii() and value.isdigit()):issues[key]=label+'는 숫자로 입력하세요.'
        elif key=='R3_BRIDGE_URL':
            if not bridge_url_valid(value):issues[key]='Bridge 배포 주소는 https://script.google.com/macros/s/…/exec 형식이어야 합니다.'
        elif key in ('R3_GEMINI_MODEL','R3_IMAGE_MODEL') and not re.fullmatch(r'[A-Za-z0-9._-]+',value):issues[key]=label+' 형식을 확인하세요.'
        elif key=='R3_GSC_PROPERTY':
            try:valid=value.startswith('sc-domain:') and len(value)>10 or urlparse(value).scheme in ('https','http') and urlparse(value).hostname
            except ValueError:valid=False
            if not valid:issues[key]='Search Console 속성 형식을 확인하세요.'
    return issues

def require_settings(values,action):
    if action not in KNOWN_ACTIONS:raise ValueError('알 수 없는 작업')
    if action in LOCAL_ACTIONS:return
    required={'R3_BLOG_ID','R3_BRIDGE_URL','R3_BRIDGE_SECRET'}
    if action in AI_ACTIONS:required|={'R3_GEMINI_KEY','R3_GEMINI_MODEL'}
    if action in ('generate_images','repair_image_generate','replace_post','replace_all','replace_resume'):required.add('R3_IMAGE_MODEL')
    issues=problems(values)
    missing=[issues[k] for k in LABELS if k in required and k in issues]
    if missing:raise ValueError('연결 설정에서 다음 항목을 확인하세요.\n'+'\n'.join(missing))

def readiness_text(values):
    issues=problems(values)
    lines=['연결 준비 상태 · 입력 형식만 검사하며 실제 API 연결은 확인하지 않습니다.']
    for key,label in LABELS.items():lines.append(label+': '+(issues.get(key) or '입력됨 · 실제 연결 미확인'))
    if bool(values.get('R3_GSC_TOKEN'))!=bool(values.get('R3_GSC_PROPERTY')):lines.append('Search Console은 접근 토큰과 속성 주소를 함께 입력해야 합니다. 없으면 공개 상태만 검사합니다.')
    lines.append('쓰기 권한·모델 사용 권한·토큰 만료는 실제 연결 시험에서 별도 확인해야 합니다.')
    return '\n'.join(lines)
