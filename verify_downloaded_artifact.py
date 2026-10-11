"""Verify the actual uploaded/downloaded artifact before delivering its link."""
import argparse,json,subprocess
from pathlib import Path
from verify_release import verify

REQUIRED_PSL={name+'/_internal/tldextract/.tld_set_snapshot'
              for name in ('Studio','Diagnostics')}

def package_root(folder):
    root=Path(folder).resolve()
    if (root/'manifest.json').is_file():return root
    candidates=[p.parent for p in root.glob('R3_0_Windows_Dev_*/manifest.json')]
    if len(candidates)!=1:raise ValueError('내려받은 묶음에 배포 manifest가 하나 있어야 합니다.')
    return candidates[0]

def check(folder,smoke=False):
    root=package_root(folder)
    result=verify(root) # Checks every manifest file, including hidden resources.
    manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
    files=manifest['files']
    if not REQUIRED_PSL<=set(files):
        raise ValueError('내려받은 묶음의 필수 출처 판정 파일 기록 누락')
    if any(not (root/name).is_file() or (root/name).stat().st_size==0 for name in REQUIRED_PSL):
        raise ValueError('내려받은 묶음의 필수 출처 판정 파일 누락 또는 빈 파일')
    result.update(downloaded_artifact_integrity='PASS',psl_files=sorted(REQUIRED_PSL),
                  app_version=manifest.get('app_version'),downloaded_executable_smoke={})
    if smoke:
        for directory,name in [('Studio','R3_Blogger_Studio'),('Diagnostics','R3_Blogger_Diagnostics')]:
            executable=root/directory/(name+'.exe')
            # This entry point uses a temporary DEMO profile; no live-account calls.
            subprocess.run([str(executable),'--smoke-test'],cwd=root,check=True,timeout=60)
            result['downloaded_executable_smoke'][name]='PASS'
            print('Downloaded Windows artifact UI/DPAPI/PSL smoke PASS:',name)
    # Windows runner execution is separate from the user's PC / account checks.
    result['account_integration_verified']=False
    return result

def main():
    parser=argparse.ArgumentParser(description='실제 GitHub 다운로드 묶음 검사')
    parser.add_argument('folder');parser.add_argument('--smoke-test',action='store_true')
    args=parser.parse_args()
    print(json.dumps(check(args.folder,args.smoke_test),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
