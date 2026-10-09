"""Daily consistent SQLite snapshots; never copy credentials or rewrite live DB."""
import sqlite3
from contextlib import closing
from datetime import datetime,timezone
from pathlib import Path

def snapshot(database,directory,keep=7,day=None):
    database=Path(database);directory=Path(directory)
    if not database.is_file():return None
    if keep<1:raise ValueError('백업 보관 수는 1개 이상이어야 합니다.')
    day=day or datetime.now(timezone.utc).strftime('%Y%m%d')
    if len(day)!=8 or not day.isascii() or not day.isdigit():raise ValueError('백업 날짜 형식 오류')
    directory.mkdir(parents=True,exist_ok=True)
    target=directory/(database.stem+'_'+day+'.sqlite3');temp=target.with_suffix('.tmp')
    if target.exists():
        with closing(sqlite3.connect(target.resolve().as_uri()+'?mode=ro',uri=True)) as saved:
            if saved.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('기존 백업 검사 실패: 원본은 유지됩니다.')
        return target
    try:
        source=sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True,timeout=10)
        dest=None
        try:
            dest=sqlite3.connect(temp)
            source.backup(dest)
            if dest.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('백업 검사 실패: 원본은 유지됩니다.')
        finally:
            if dest:dest.close()
            source.close()
        temp.replace(target)
    except Exception:
        temp.unlink(missing_ok=True);raise
    older=sorted(directory.glob(database.stem+'_????????.sqlite3'),reverse=True)
    for old in older[keep:]:old.unlink()
    return target

def daily_snapshots(base):
    base=Path(base)
    return [result for name in ('studio.sqlite3','demo.sqlite3') if (result:=snapshot(base/name,base/'backups')) is not None]

def inventory(base):
    results=[]
    for path in sorted((Path(base)/'backups').glob('*.sqlite3'),reverse=True):
        item={'name':path.name,'size':path.stat().st_size,'valid':False,'counts':{}}
        try:
            with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
                if db.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('검사 실패')
                item['version']=db.execute('PRAGMA user_version').fetchone()[0]
                tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                for name in ('posts','post_versions','recovery_checks','generation_jobs','task_runs'):
                    if name in tables:item['counts'][name]=db.execute('SELECT count(*) FROM '+name).fetchone()[0]
                item['valid']=True
        except (OSError,sqlite3.Error,ValueError):item['reason']='백업 읽기 또는 무결성 확인 실패'
        results.append(item)
    return results

def inventory_text(items):
    labels={'posts':'글 기록','post_versions':'이전 글 버전','recovery_checks':'검사 기록','generation_jobs':'생성 작업','task_runs':'실행 기록'}
    lines=['백업 확인 · 원본 DB를 변경하거나 복원하지 않습니다.']
    for item in items:
        lines.append('\n'+item['name']+' · '+('파일 검사 정상' if item['valid'] else '확인 실패'))
        if item['valid']:lines.append(' / '.join(labels[name]+' '+str(count) for name,count in item['counts'].items()) or '프로그램 기록 테이블 없음')
    if not items:lines.append('아직 생성된 일일 백업이 없습니다. 다음 실행부터 기존 DB를 백업합니다.')
    return '\n'.join(lines)
