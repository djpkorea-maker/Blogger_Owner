"""Developer smoke check. Default demo; --live explicitly enables read-only Blogger."""
import argparse
import json
import os
import platform
import tempfile
from collections import Counter
from pathlib import Path
from r3studio import __version__
from r3studio.sync import Store,Sync
from r3studio.gates import run_checks

def inspect(adapter,mode,path):
    store=Store(path)
    try:
        first=Sync(store,adapter,adapter.blog_id).run()
        checks=run_checks(store,adapter.blog_id)
        second=Sync(store,adapter,adapter.blog_id).run()
        grades=dict(Counter(r[0] for r in store.db.execute('SELECT grade FROM posts WHERE present=1')))
        return {'version':__version__,'mode':mode,'platform':platform.system(),
                'first_sync':first,'second_sync':second,'fast_checks':checks,'grades':grades,
                'writes_performed':False,'ai_calls_performed':False,
                'windows_gui_verified':False,'full_release_verified':False}
    finally:store.close()

def main(argv=None):
    parser=argparse.ArgumentParser(description='R3.0 개발자용 읽기 전용 연결 점검')
    parser.add_argument('--live',action='store_true',help='명시적으로 실제 Blogger 목록/본문 조회')
    args=parser.parse_args(argv)
    try:
        if args.live:
            from r3studio.readiness import require_settings
            from r3studio.bridge import BridgeAdapter
            require_settings(os.environ,'sync');adapter=BridgeAdapter.from_environment();mode='LIVE_READ_ONLY'
        else:
            from r3studio.app import DemoAdapter
            adapter=DemoAdapter();adapter.blog_id='demo';mode='DEMO'
        with tempfile.TemporaryDirectory(prefix='r3_release_check_') as folder:
            result=inspect(adapter,mode,str(Path(folder)/'check.sqlite3'))
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except Exception as exc:
        print(json.dumps({'status':'FAILED','error_type':type(exc).__name__,
                          'message':'연결 설정과 진단 기록을 확인하세요. 최종판 검증은 완료되지 않았습니다.'},ensure_ascii=False));return 1

if __name__=='__main__':raise SystemExit(main())
