"""Developer-only Windows build; never install dependencies or access accounts."""
import hashlib
import json
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT=Path(__file__).resolve().parent
BUILD_REQUIREMENTS=ROOT/'requirements-build.txt'

def build_commands(python=sys.executable):
    base=[python,'-m','PyInstaller','--noconfirm','--clean','--onedir',
          '--distpath',str(ROOT/'dist'),'--workpath',str(ROOT/'build'),
          '--specpath',str(ROOT/'build'),'--paths',str(ROOT)]
    return [base+['--windowed','--name','R3_Blogger_Studio',str(ROOT/'desktop_entry.py')],
            base+['--console','--name','R3_Blogger_Diagnostics',str(ROOT/'diagnose.py')]]

def bundle(release,smoke_results=None):
    # Explicit documents only; no database, credentials, user assets, or source uploads.
    outputs=[(ROOT/'dist/R3_Blogger_Studio','Studio'),(ROOT/'dist/R3_Blogger_Diagnostics','Diagnostics')]
    if not release.is_dir() or any(release.iterdir()):raise RuntimeError('새 빈 배포 폴더가 필요합니다.')
    for source,name in outputs:
        exe=source/(source.name+'.exe')
        if not source.is_dir() or not exe.is_file() or exe.stat().st_size==0:raise RuntimeError('실행 파일 빌드 결과 없음 또는 빈 파일')
        for path in source.rglob('*'):
            if path.is_symlink():raise RuntimeError('배포 폴더 외부 연결 발견: 묶음 생성 중지')
            if path.is_file() and (path.suffix.lower() in ('.sqlite3','.db','.bak','.jsonl')
                or path.name.lower() in ('settings.json','.env') or path.name.lower().startswith('.env.')):
                raise RuntimeError('사용자 기록 또는 설정 파일 발견: 묶음 생성 중지')
    for name in ('QUICK_START_KO.md','WINDOWS_VALIDATION.md'):
        if not (ROOT/name).is_file():raise RuntimeError('배포 안내 문서 누락')
    for source,name in outputs:
        shutil.copytree(source,release/name)
    for name in ('QUICK_START_KO.md','WINDOWS_VALIDATION.md'):
        shutil.copy2(ROOT/name,release/name)
    hashes={str(p.relative_to(release)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in release.rglob('*') if p.is_file()}
    from r3studio import __version__
    (release/'manifest.json').write_text(json.dumps({'status':'WINDOWS_BUILD_UNVERIFIED','app_version':__version__,
        'python':platform.python_version(),'windows_runner_smoke':smoke_results or {},'user_pc_verified':False,'account_integration_verified':False,'files':hashes},ensure_ascii=False,indent=2),encoding='utf-8')
    from verify_release import verify
    verify(release)
    target=release.parent/(release.name+'.zip')
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as z:
        for p in release.rglob('*'):
            if p.is_file():z.write(p,p.relative_to(release.parent))
    return target

def main():
    if platform.system()!='Windows':raise SystemExit('Windows PC에서만 EXE 빌드를 실행합니다. 현재 환경에서는 생성하지 않습니다.')
    from build_preflight import inspect
    preflight=inspect()
    if not preflight['ready_to_attempt_build']:raise SystemExit('Windows 빌드 준비 미완료: '+', '.join(preflight['missing']))
    # No network or credentials needed for these unit tests.
    subprocess.run([sys.executable,'-m','unittest','discover'],cwd=ROOT,check=True)
    subprocess.run(['node','test_bridge_hash.js'],cwd=ROOT,check=True)
    subprocess.run([sys.executable,str(ROOT/'diagnose.py'),'--smoke-test'],cwd=ROOT,check=True,timeout=60)
    for command in build_commands():subprocess.run(command,cwd=ROOT,check=True)
    smoke_results={}
    for name in ('R3_Blogger_Studio','R3_Blogger_Diagnostics'):
        executable=ROOT/'dist'/name/(name+'.exe')
        subprocess.run([str(executable),'--smoke-test'],cwd=ROOT,check=True,timeout=60)
        smoke_results[name]='PASS'
        print('Windows runner UI/DPAPI smoke PASS:',name)
    from datetime import datetime
    release=ROOT/'release'/('R3_0_Windows_Dev_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'))
    release.mkdir(parents=True)
    print('Build bundle:',bundle(release,smoke_results))
    print('Windows 화면/설정/중단/실계정 검증 전입니다. 설치용 최종판으로 배포하지 마세요.')

if __name__=='__main__':main()
