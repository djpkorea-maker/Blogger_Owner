"""Offline registrable domains for source diversity; never a truth verdict."""
import ipaddress
import re
from urllib.parse import urlsplit
from tldextract import TLDExtract

# Pinned bundled PSL only: no network, account calls or user cache data.
_EXTRACT = TLDExtract(suffix_list_urls=(), cache_dir=None,
                      include_psl_private_domains=True)
DOMAIN_RULE_VERSION = 'psl-offline-5.3.0-private-v1'

class DomainResourceError(RuntimeError):
    def __init__(self):
        message='프로그램의 출처 판정 파일이 누락되거나 손상되었습니다. 새 시험판 압축을 새 폴더에 전체 해제하세요. 설정·DB·본문·이미지는 보존하세요.'
        super().__init__(message)
        self.diagnostic={'reason':'PACKAGE_RESOURCE_MISSING','summary':message,
                         'stage':'프로그램 필수 파일 확인','claims_evaluated':False,
                         'failure_phase':'APPLICATION_RESOURCE',
                         'action':'완전한 배포 묶음으로 다시 실행한 뒤 기존 수정안의 최종 검증을 진행하세요.'}

def registered_domain(url):
    if not isinstance(url,str):return ''
    try:
        parsed=urlsplit(url)
        if parsed.scheme not in ('http','https') or parsed.username is not None or parsed.password is not None:return ''
        parsed.port # Reject malformed ports; ports do not define a publisher.
        host=(parsed.hostname or '').rstrip('.').encode('idna').decode('ascii').lower()
        labels=host.split('.')
        if len(labels)<2 or len(host)>253 or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',x) for x in labels):return ''
    except (ValueError,UnicodeError,TypeError):return ''
    try:
        ipaddress.ip_address(host)
        return '' # IP addresses cannot stand in for independent publishers.
    except ValueError:pass
    try:value=_EXTRACT(host)
    except (OSError,LookupError):raise DomainResourceError() from None
    if value.suffix:
        return value.top_domain_under_public_suffix if value.domain else ''
    # PSL's implicit "*" rule for unlisted suffixes, including reserved
    # .example fixtures. Arbitrary subdomains never count independently.
    return '.'.join(labels[-2:])

def check_domain_resources():
    # Exercise the actual loader at normal startup as well as packaged smoke tests.
    if (registered_domain('https://www.samsungsvc.co.kr/')!='samsungsvc.co.kr'
        or registered_domain('https://www.lge.co.kr/')!='lge.co.kr'
        or registered_domain('https://one.blogspot.com/')!='one.blogspot.com'):
        raise DomainResourceError()

_PRECLAIM_SUMMARIES={'확인된 독립 출처 2개 미만','직접 확인 가능한 원문 2개 미만',
                     '원문 검사 응답 형식 오류'}
def claims_not_evaluated(diagnostic):
    if not isinstance(diagnostic,dict):return False
    return (diagnostic.get('claims_evaluated') is False
            or diagnostic.get('failure_phase') in ('ORIGINAL_ACCESS','SOURCE_INDEPENDENCE','REVIEW_FORMAT')
            or diagnostic.get('summary') in _PRECLAIM_SUMMARIES)
