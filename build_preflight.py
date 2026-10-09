"""Offline developer build checks; no installs, credentials, or API requests."""
import importlib.util
import json
import platform
import shutil
import sys

def inspect(system=None,version=None,find=None,which=None):
    system=system or platform.system();version=version or sys.version_info[:2]
    find=find or importlib.util.find_spec;which=which or shutil.which
    checks={'windows':system=='Windows','python_3_12':tuple(version)==(3,12),
            'tkinter':find('tkinter') is not None,'pillow':find('PIL') is not None,
            'pyinstaller':find('PyInstaller') is not None,'node':which('node') is not None}
    return {'ready_to_attempt_build':all(checks.values()),'checks':checks,
            'missing':[name for name,passed in checks.items() if not passed],
            'windows_execution_verified':False,'account_integration_verified':False}

def main():
    result=inspect();print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['ready_to_attempt_build'] else 1

if __name__=='__main__':raise SystemExit(main())
