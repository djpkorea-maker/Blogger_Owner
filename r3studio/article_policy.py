"""Shared generated-article policy: prose length, factual boundaries and placement."""
import html,re
from .captions import Tree,Node,VOID
from .gates import Document,normalize,fast_check,TARGET_TEXT_LENGTH,TARGET_MAX_TEXT_LENGTH

VERSION='R3.0-article-0.81'
MIN_BODY_LENGTH=TARGET_TEXT_LENGTH
TARGET_BODY_LENGTH=2200
AUXILIARY={'참고 자료','참고자료','참고 문헌','참고문헌','출처','references','함께 읽으면 도움이 되는 글','관련 글'}
BOUNDARY_RULES=('제품·모델·연도·기능 지원 여부와 원문의 적용 조건을 유지하세요. '
    '이상/이하와 이내/이후, 정지/오류/방전, 표시등과 충전 상태를 서로 바꾸거나 합치지 마세요. '
    '숫자가 같은 것만으로 근거가 일치하지 않습니다. 시간의 시작 조건·단위·비교 방향을 대조하세요. '
    '특정 모델의 재개·분리·청소·이동 절차를 모든 제품의 공통 절차로 일반화하지 마세요. '
    '반복 횟수나 권장 재개 모드는 원문에 있어야 합니다. 없으면 임의의 횟수·모드를 만들지 마세요. '
    '센서 종류만으로 앱 기능 지원 여부를 단정하지 마세요. 기능은 실제 모델 설명서로 확인하세요. '
    '원문에 필요한 선행 조건·순서·금지 사항이 있으면 이를 빠뜨리지 마세요. '
    '검색 의도에 필요한 상태 확인·행동 순서·적용 조건·중단 및 후속 조치가 설명되어야 합니다. '
    '자료를 길게 나열하거나 반복 문장으로 분량을 채우지 마세요.')

def auxiliary(node):
    return isinstance(node,Node) and (node.attrs.get('data-r3-kind') in ('related','references')
        or node.tag=='h2' and normalize(node.text()) in AUXILIARY)

def prose_parts(children):
    skipping=False
    for node in children:
        if isinstance(node,str):
            if not skipping:yield node
            continue
        if node.tag=='h2':skipping=auxiliary(node)
        if skipping or auxiliary(node) or node.tag in ('script','style','template','iframe','figure','figcaption','nav','footer','aside'):continue
        yield from prose_parts(node.children)

def body_text(content):
    return normalize(' '.join(prose_parts(Tree(content).root.children)))

def body_metrics(content):
    length=len(body_text(content))
    return {'body_text_length':length,'body_minimum':MIN_BODY_LENGTH,
            'body_deficit':max(0,MIN_BODY_LENGTH-length),'body_target':TARGET_BODY_LENGTH,
            'measurement':'HTML・ALT・그림 설명・참고 목록・관련 글 제외, 소제목 포함・공백 정규화'}

def generated_fast(post,others=()):
    result=fast_check(post,others);metrics=body_metrics(post['content'])
    result.metrics.update(metrics)
    result.issues=[i for i in result.issues if i!='본문 길이 검토 필요']
    if metrics['body_deficit']:result.issues.insert(0,'본문 길이 검토 필요')
    return result

def render(node):
    if isinstance(node,str):return html.escape(node,quote=False)
    if not node.tag:return ''.join(render(c) for c in node.children)
    attrs=''.join(' '+k+('="'+html.escape(str(v),quote=True)+'"' if v is not None else '') for k,v in node.attrs.items())
    return '<'+node.tag+attrs+'>'+('' if node.tag in VOID else ''.join(render(c) for c in node.children)+'</'+node.tag+'>')

def strip_auxiliary(content):
    root=Tree(content).root
    def clean(node):
        children=[];skipping=False
        for child in node.children:
            if isinstance(child,Node) and child.tag=='h2':skipping=auxiliary(child)
            if skipping or auxiliary(child):continue
            if isinstance(child,Node):clean(child)
            children.append(child)
        node.children=children
    clean(root)
    result=render(root)
    if Document(result).errors:raise ValueError('참고 자료 정리 후 HTML 구조 확인 필요')
    return result

def sections(content):
    root=Tree(content).root
    headings=[n for n in root.nodes() if n.tag=='h2' and not auxiliary(n)
              and not any(auxiliary(a) or a.tag in ('figure','figcaption','nav','footer','aside','script','style','template') for a in ancestors(n))]
    return root,headings

def ancestors(node):
    parent=node.parent
    while parent is not None:
        yield parent;parent=parent.parent

def section_text(heading):
    siblings=heading.parent.children;index=siblings.index(heading)+1;parts=[heading.text()]
    for node in siblings[index:]:
        if auxiliary(node) or isinstance(node,Node) and node.tag=='h2':break
        parts.extend(prose_parts([node]))
    return normalize(' '.join(parts))

def select_sections(content,candidates):
    _,headings=sections(content)
    if len(headings)<2:raise ValueError('이미지 배치할 본문 H2 구역 2개 필요')
    selected=[]
    for slot,candidate in enumerate(candidates):
        requested=candidate.get('placement_section')
        if requested is not None:
            if type(requested) is not int or not 1<=requested<=len(headings):raise ValueError('이미지 배치 구역 번호 불일치')
            index=requested-1
        else:
            text=' '.join(str(candidate.get(k,'')) for k in ('alt','caption'))
            text+=' '+str(candidate.get('review',{}).get('observed',''))
            tokens={x for x in re.findall(r'[가-힣A-Za-z]{2,}',text.lower()) if len(x)>=2}
            scores=[sum(3 if token in normalize(h.text()) else 1 if token in section_text(h) else 0 for token in tokens) for h in headings]
            available=[i for i in range(len(headings)) if i not in selected]
            best=max(available,key=lambda i:scores[i])
            index=best if scores[best]>0 else (0 if slot==0 else min(len(headings)-1,max(1,len(headings)//2)))
            if index in selected:index=available[0]
        if index in selected:raise ValueError('두 이미지는 서로 다른 본문 구역에 배치해야 합니다.')
        selected.append(index)
    return [i+1 for i in selected]

def place_figures(content,blocks,candidates):
    if len(blocks)!=2 or len(candidates)!=2:raise ValueError('이미지 구역 2개 필요')
    if Document(content).images:raise ValueError('기존 이미지가 있는 본문에는 자동 추가할 수 없습니다.')
    selected=select_sections(content,candidates);root,headings=sections(content)
    for block,index in zip(blocks,selected):
        heading=headings[index-1];parent=heading.parent;siblings=parent.children
        position=siblings.index(heading)+1
        while position<len(siblings):
            node=siblings[position]
            if auxiliary(node) or isinstance(node,Node) and node.tag=='h2':break
            position+=1
        figure=Tree(block).root.children[0];figure.parent=parent;siblings.insert(position,figure)
    output=render(root)
    if Document(output).errors:raise ValueError('이미지 배치 후 HTML 구조 확인 필요')
    return output
