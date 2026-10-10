"""Associate captions by HTML structure, never by unrelated global order."""
from html.parser import HTMLParser
from .images import ImageHold

VOID={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}

class Node:
    def __init__(self,tag='',attrs=(),parent=None):
        self.tag=tag;self.attrs=dict(attrs);self.parent=parent;self.children=[]
    def nodes(self):
        yield self
        for child in self.children:
            if isinstance(child,Node):yield from child.nodes()
    def text(self):
        return ''.join(child.text() if isinstance(child,Node) else child for child in self.children)

class Tree(HTMLParser):
    def __init__(self,content):
        super().__init__();self.root=Node();self.current=self.root;self.feed(content)
    def handle_starttag(self,tag,attrs):
        node=Node(tag,attrs,self.current);self.current.children.append(node)
        if tag not in VOID:self.current=node
    def handle_startendtag(self,tag,attrs):
        self.current.children.append(Node(tag,attrs,self.current))
    def handle_endtag(self,tag):
        node=self.current
        while node.parent:
            if node.tag==tag:self.current=node.parent;return
            node=node.parent
    def handle_data(self,data):self.current.children.append(data)

def image_captions(content):
    root=Tree(content).root;items=[];used=set()
    for image in (node for node in root.nodes() if node.tag=='img'):
        container=image.parent
        while container.parent and container.tag not in ('figure','div'):
            container=container.parent
        captions=[]
        if container.tag=='figure':
            if sum(n.tag=='img' for n in container.nodes())==1:
                captions=[n for n in container.nodes() if n.tag=='figcaption']
        elif container.tag=='div' and 'separator' in container.attrs.get('class','').split():
            siblings=container.parent.children;index=siblings.index(container)+1
            while index<len(siblings) and isinstance(siblings[index],str) and not siblings[index].strip():index+=1
            if index<len(siblings):
                following=siblings[index]
                if (isinstance(following,Node) and following.tag=='div'
                    and 'abs-v23-caption' in following.attrs.get('class','').split()
                    and sum(n.tag=='img' for n in container.nodes())==1):captions=[following]
        if len(captions)!=1 or id(captions[0]) in used:
            raise ImageHold('공개 이미지와 설명문 연결 확인 필요')
        caption=captions[0]
        if any(n.tag in ('img','script','style') for n in caption.nodes()) or not caption.text().strip():
            raise ImageHold('이미지 설명문 내용 확인 필요')
        used.add(id(caption));items.append(' '.join(caption.text().split()))
    return items

def replace_image_text(content,suggestions):
    """Apply pixel-derived text by image order to an explicit caption container."""
    import html
    root=Tree(content).root
    images=[n for n in root.nodes() if n.tag=='img']
    for item in suggestions:
        image=images[item['index']-1]
        if image.attrs.get('src','')!=item['url']:raise ImageHold('ALT 수정 대상 이미지 변경')
        image.attrs['alt']=item['suggested_text']['alt']
        if 'title' in image.attrs:image.attrs['title']=item['suggested_text']['alt']
        container=image.parent
        while container.parent and container.tag not in ('figure','div'):container=container.parent
        caption=None
        if container.tag=='figure' and sum(n.tag=='img' for n in container.nodes())==1:
            found=[n for n in container.nodes() if n.tag=='figcaption']
            if len(found)==1:caption=found[0]
        elif container.tag=='div' and 'separator' in container.attrs.get('class','').split():
            siblings=container.parent.children;index=siblings.index(container)+1
            while index<len(siblings) and isinstance(siblings[index],str) and not siblings[index].strip():index+=1
            if index<len(siblings) and isinstance(siblings[index],Node) and 'abs-v23-caption' in siblings[index].attrs.get('class','').split():caption=siblings[index]
        if caption is None:raise ImageHold('설명문 수정 위치 확인 필요: 명확한 이미지별 설명 구조가 필요합니다.')
        caption.children=[item['suggested_text']['caption']]
    def render(node):
        if isinstance(node,str):return html.escape(node,quote=False)
        inner=''.join(render(child) for child in node.children)
        if not node.tag:return inner
        attrs=''.join(' '+key+('="'+html.escape(str(value),quote=True)+'"' if value is not None else '') for key,value in node.attrs.items())
        return '<'+node.tag+attrs+'>'+('' if node.tag in VOID else inner+'</'+node.tag+'>')
    return render(root)
