"""Settings persistence. Windows secrets use current-user DPAPI, never plaintext."""
import base64
import ctypes
import json
import os
from pathlib import Path

FIELDS={'R3_BLOG_ID','R3_BRIDGE_URL','R3_BRIDGE_SECRET','R3_GEMINI_KEY','R3_GEMINI_MODEL','R3_IMAGE_MODEL','R3_GSC_TOKEN','R3_GSC_PROPERTY','R3_START_MODE','R3_AUTO_SYNC'}
SECRET_FIELDS={'R3_BRIDGE_SECRET','R3_GEMINI_KEY','R3_GSC_TOKEN'}

class SettingsError(RuntimeError):pass

def dpapi(data,decrypt=False):
    if os.name!='nt':raise SettingsError('이 PC에서는 비밀값 저장을 지원하지 않습니다. 세션에서만 사용합니다.')
    from ctypes import wintypes
    class Blob(ctypes.Structure):_fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
    buffer=(ctypes.c_ubyte*len(data)).from_buffer_copy(data);source=Blob(len(data),buffer);out=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.LocalFree.argtypes=[wintypes.HLOCAL];kernel.LocalFree.restype=wintypes.HLOCAL
    func=crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    func.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)];func.restype=wintypes.BOOL
    if not func(ctypes.byref(source),None,None,None,None,1,ctypes.byref(out)):raise SettingsError('Windows 비밀값 암호화/복호화 실패')
    try:return ctypes.string_at(out.data,out.size)
    finally:kernel.LocalFree(ctypes.cast(out.data,ctypes.c_void_p))

class Settings:
    def __init__(self,path,protect=None,unprotect=None):
        self.path=Path(path);self.protect=protect or (lambda b:dpapi(b));self.unprotect=unprotect or (lambda b:dpapi(b,True))
    def save(self,values):
        stored={}
        for key,value in values.items():
            if key not in FIELDS or not isinstance(value,str):raise SettingsError('설정 형식 오류')
            value=value.strip()
            if key=='R3_AUTO_SYNC' and value not in ('0','1'):raise SettingsError('자동 조회 설정 형식 오류')
            if key=='R3_START_MODE' and value not in ('DEMO','LIVE'):raise SettingsError('시작 모드는 데모 또는 실제 조회로 선택하세요.')
            stored[key]={'encrypted':base64.b64encode(self.protect(value.encode())).decode()} if key in SECRET_FIELDS and value else value
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps(stored,ensure_ascii=False),encoding='utf-8');temp.replace(self.path)
    def load(self):
        if not self.path.exists():return {}
        try:
            stored=json.loads(self.path.read_text(encoding='utf-8'));values={}
            if not isinstance(stored,dict):raise SettingsError('설정 데이터 손상')
            for key,value in stored.items():
                if key not in FIELDS:continue
                if isinstance(value,dict):values[key]=self.unprotect(base64.b64decode(value['encrypted'])).decode()
                elif key in SECRET_FIELDS and value:raise SettingsError('암호화되지 않은 비밀값 발견')
                elif isinstance(value,str):values[key]=value
                else:raise SettingsError('설정 데이터 손상')
            return values
        except (OSError,ValueError,KeyError,TypeError,UnicodeError):raise SettingsError('설정 읽기 실패') from None
    def activate(self,values):
        for key in FIELDS:
            if key in values:os.environ[key]=values[key]
