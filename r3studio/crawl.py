"""Public robots and bounded sitemap observations, separate from indexing proof."""
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse,urljoin,quote
from .sync import now
from .freshness import is_fresh


def robots_rules(text,url):
    groups=[];agents=[];rules=[];maps=[];seen_directive=False
    for raw in text.lstrip('\ufeff').splitlines():
        line=raw.split('#',1)[0].strip()
        if ':' not in line:continue
        key,value=[s.strip() for s in line.split(':',1)];key=key.lower()
        if key=='sitemap':maps.append(value);continue
        if key=='user-agent':
            if seen_directive:groups.append((agents,rules));agents=[];rules=[];seen_directive=False
            agents.append(value.lower())
        elif key in ('allow','disallow') and agents:
            seen_directive=True
            if value.startswith('/'):rules.append((key,value))
    if agents:groups.append((agents,rules))
    ranked=[]
    for agents,rules in groups:
        specific=[len(a) for a in agents if a!='*' and a in 'googlebot']
        if specific:ranked.append((max(specific),rules))
        elif '*' in agents:ranked.append((0,rules))
    chosen=[]
    if ranked:
        best=max(n for n,_ in ranked);chosen=[rule for n,group in ranked if n==best for rule in group]
    parsed=urlparse(url);path=parsed.path or '/'
    if parsed.query:path+='?'+parsed.query
    # Keep existing percent escapes and encode non-ASCII URL path bytes.
    path=quote(path,safe='/%?=&:+,;@!$()*-._~')
    matches=[]
    for kind,pattern in chosen:
        end=pattern.endswith('$');literal=pattern[:-1] if end else pattern
        expression='^'+re.escape(literal).replace(r'\*','.*')+('$' if end else '')
        if re.search(expression,path):matches.append((len(literal.replace('*','').encode()),kind=='allow',pattern))
    if not matches:return {'state':'ALLOWED','matched_rule':None,'sitemaps':maps}
    _,allow,pattern=max(matches,key=lambda x:(x[0],x[1]))
    return {'state':'ALLOWED' if allow else 'BLOCKED','matched_rule':pattern,'sitemaps':maps}

class CrawlInspector:
    def __init__(self,store,fetch):
        self.store,self.fetch=store,fetch
        store.db.execute('CREATE TABLE IF NOT EXISTS crawl_documents(url TEXT PRIMARY KEY,checked_at TEXT,payload TEXT)');store.db.commit()
    def document(self,url):
        old=self.store.db.execute('SELECT * FROM crawl_documents WHERE url=?',(url,)).fetchone()
        if old and is_fresh(old['checked_at'],3600):
            try:cached=json.loads(old['payload'])
            except (ValueError,TypeError):cached=None
            if (isinstance(cached,dict) and type(cached.get('status')) is int
                and isinstance(cached.get('body'),str)):return cached
        response=self.fetch(url)
        with self.store.db:self.store.db.execute('INSERT OR REPLACE INTO crawl_documents VALUES(?,?,?)',(url,now(),json.dumps(response,ensure_ascii=False)))
        return response
    def inspect(self,url,max_documents=20):
        parsed=urlparse(url);root=parsed.scheme+'://'+parsed.netloc
        out={'robots_url':root+'/robots.txt','robots_state':'UNKNOWN','sitemap_state':'UNKNOWN','sitemap_checked':[]}
        declared=[]
        try:
            response=self.document(out['robots_url']);status=response['status']
            if 200<=status<300:
                rules=robots_rules(response['body'][:500*1024],url);out['robots_state']=rules['state'];out['matched_rule']=rules['matched_rule'];declared=rules['sitemaps']
            elif 400<=status<500 and status!=429:out['robots_state']='NO_FILE_NO_RESTRICTION'
            else:out['robots_state']='UNKNOWN_HTTP_'+str(status)
        except (OSError,ValueError):pass
        queue=declared or [root+'/sitemap.xml'];seen=set();complete=True;found=False
        while queue and len(seen)<max_documents:
            current=queue.pop(0)
            if current in seen:continue
            seen.add(current)
            # Cross-host declarations may be legitimate; leave for manual review.
            if urlparse(current).hostname!=parsed.hostname:complete=False;continue
            try:
                response=self.document(current)
                if not 200<=response['status']<300:complete=False;continue
                body=response['body']
                if '<!DOCTYPE' in body.upper() or '<!ENTITY' in body.upper():complete=False;continue
                xml=ET.fromstring(body);kind=xml.tag.rsplit('}',1)[-1]
                locations=[e.text.strip() for e in xml.iter() if e.tag.rsplit('}',1)[-1]=='loc' and e.text]
                out['sitemap_checked'].append(current)
                if kind=='sitemapindex':queue.extend(locations)
                elif kind=='urlset':found=found or url in locations
                else:complete=False
            except (OSError,ValueError,ET.ParseError):complete=False
            if found:break
        out['sitemap_state']='FOUND' if found else 'NOT_LISTED' if complete and not queue and out['sitemap_checked'] else 'UNKNOWN_OR_PARTIAL'
        return out
