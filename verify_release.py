"""Verify packaged files without executing any binary or accessing accounts."""
import argparse
import hashlib
import json
from pathlib import Path,PurePosixPath

def verify(folder):
    root=Path(folder).resolve()
    try:manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):raise ValueError('배포 manifest 누락 또는 손상') from None
    if not isinstance(manifest,dict) or not isinstance(manifest.get('files'),dict):raise ValueError('배포 manifest 형식 오류')
    files=manifest['files']
    required={'Studio/R3_Blogger_Studio.exe','Diagnostics/R3_Blogger_Diagnostics.exe','QUICK_START_KO.md','WINDOWS_VALIDATION.md'}
    if not required<=set(files):raise ValueError('필수 실행 파일 또는 안내 문서 기록 누락')
    for name,expected in files.items():
        path=PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name or str(path)!=name:raise ValueError('배포 경로 형식 오류')
        local=root.joinpath(*path.parts)
        if not local.resolve().is_relative_to(root) or local.is_symlink():raise ValueError('배포 외부 파일 연결 발견')
        if not isinstance(expected,str) or not local.is_file():raise ValueError('배포 파일 누락')
        if hashlib.sha256(local.read_bytes()).hexdigest()!=expected:raise ValueError('배포 파일 변경 또는 손상')
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file() and p.name!='manifest.json'}
    if actual!=set(files):raise ValueError('manifest에 없는 파일 발견')
    return {'file_integrity':'PASS','checked_files':len(files),'package_status':manifest.get('status','UNKNOWN'),
            'windows_execution_verified':False,'account_integration_verified':False}

def main():
    parser=argparse.ArgumentParser(description='R3.0 배포 파일 무결성 검사 · EXE 실행 없음')
    parser.add_argument('folder');args=parser.parse_args()
    try:print(json.dumps(verify(args.folder),ensure_ascii=False,indent=2));return 0
    except ValueError as exc:print(str(exc));return 1

if __name__=='__main__':raise SystemExit(main())
