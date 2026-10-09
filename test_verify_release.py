import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from verify_release import verify

class Tests(unittest.TestCase):
    def package(self,folder):
        root=Path(folder);files={}
        for name in ('Studio/R3_Blogger_Studio.exe','Diagnostics/R3_Blogger_Diagnostics.exe','QUICK_START_KO.md','WINDOWS_VALIDATION.md'):
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'mock artifact');files[name]=hashlib.sha256(p.read_bytes()).hexdigest()
        (root/'manifest.json').write_text(json.dumps({'status':'WINDOWS_BUILD_UNVERIFIED','files':files}))
        return root
    def test_integrity_does_not_claim_execution_verification(self):
        with tempfile.TemporaryDirectory() as d:
            result=verify(self.package(d));self.assertEqual(result['file_integrity'],'PASS')
            self.assertFalse(result['windows_execution_verified']);self.assertFalse(result['account_integration_verified'])
    def test_missing_changed_extra_and_unsafe_files_fail(self):
        for failure in ('missing','changed','extra','unsafe'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as d:
                root=self.package(d);p=root/'Studio/R3_Blogger_Studio.exe'
                if failure=='missing':p.unlink()
                elif failure=='changed':p.write_bytes(b'changed')
                elif failure=='extra':(root/'settings.json').write_text('private')
                else:
                    manifest=json.loads((root/'manifest.json').read_text());manifest['files']['../outside']='hash';(root/'manifest.json').write_text(json.dumps(manifest))
                with self.assertRaises(ValueError):verify(root)
