"""Reproduce hidden-file upload loss, then validate the downloaded distribution."""
import hashlib,json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch,Mock
from verify_downloaded_artifact import check,package_root,REQUIRED_PSL
from r3studio.source_domains import registered_domain,check_domain_resources,DomainResourceError

class Tests(unittest.TestCase):
    def package(self,parent):
        root=Path(parent)/'R3_0_Windows_Dev_fixture';files={}
        for name in ('Studio/R3_Blogger_Studio.exe','Diagnostics/R3_Blogger_Diagnostics.exe',
                     'QUICK_START_KO.md','WINDOWS_VALIDATION.md',*sorted(REQUIRED_PSL)):
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
            p.write_bytes(b'mock packaged resource')
            files[name]=hashlib.sha256(p.read_bytes()).hexdigest()
        (root/'manifest.json').write_text(json.dumps({'status':'WINDOWS_BUILD_UNVERIFIED',
                         'app_version':'3.0.0.dev86','files':files}),encoding='utf-8')
        return root

    def transfer(self,folder,include_hidden):
        # ZIP fixtures reproduce the uploader's documented hidden-file exclusion.
        original=self.package(Path(folder)/'built')
        archive=Path(folder)/'uploaded.zip'
        with zipfile.ZipFile(archive,'w') as z:
            for p in original.rglob('*'):
                if p.is_file() and (include_hidden or not any(v.startswith('.') for v in p.relative_to(original).parts)):
                    z.write(p,p.relative_to(original.parent).as_posix())
        downloaded=Path(folder)/'내려받은 시험판'
        with zipfile.ZipFile(archive) as z:z.extractall(downloaded)
        return original,downloaded

    def test_dev85_hidden_file_exclusion_fails_before_executing_binaries(self):
        with tempfile.TemporaryDirectory() as d:
            original,downloaded=self.transfer(d,False)
            self.assertTrue(all((original/p).is_file() for p in REQUIRED_PSL))
            with patch('verify_downloaded_artifact.subprocess.run') as run:
                with self.assertRaisesRegex(ValueError,'배포 파일 누락'):check(downloaded,smoke=True)
                run.assert_not_called()

    def test_include_hidden_roundtrip_preserves_all_manifest_hashes_and_both_resources(self):
        with tempfile.TemporaryDirectory() as d:
            original,downloaded=self.transfer(d,True)
            result=check(downloaded)
            self.assertEqual(result['downloaded_artifact_integrity'],'PASS')
            self.assertEqual(result['psl_files'],sorted(REQUIRED_PSL))
            self.assertEqual(result['checked_files'],6)
            self.assertEqual(result['downloaded_executable_smoke'],{})
            self.assertFalse(result['account_integration_verified'])
            for p in REQUIRED_PSL:self.assertEqual((original/p).read_bytes(),(package_root(downloaded)/p).read_bytes())

    def test_downloaded_executables_not_original_build_are_used_in_unicode_directory(self):
        with tempfile.TemporaryDirectory() as d:
            original,downloaded=self.transfer(d,True);root=package_root(downloaded)
            with patch('verify_downloaded_artifact.subprocess.run') as run:
                result=check(downloaded,True)
            self.assertEqual(run.call_count,2)
            self.assertEqual(len(result['downloaded_executable_smoke']),2)
            for call in run.call_args_list:
                self.assertTrue(Path(call.args[0][0]).is_relative_to(downloaded.resolve()))
                self.assertFalse(Path(call.args[0][0]).is_relative_to(original))
                self.assertEqual(call.args[0][1],'--smoke-test')
                self.assertEqual(call.kwargs['cwd'],root);self.assertTrue(call.kwargs['check'])

    def test_both_flat_and_single_wrapper_packages_are_supported(self):
        with tempfile.TemporaryDirectory() as d:
            root=self.package(d)
            self.assertEqual(package_root(root),root.resolve())
            self.assertEqual(package_root(d),root.resolve())
            self.assertEqual(check(root)['downloaded_artifact_integrity'],'PASS')

    def test_missing_one_resource_empty_corrupt_and_removed_manifest_entry_are_blocked(self):
        for mode in ('missing','empty','corrupt','record'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                root=self.package(d);name=sorted(REQUIRED_PSL)[0];target=root/name
                if mode=='missing':target.unlink()
                elif mode=='empty':target.write_bytes(b'')
                elif mode=='corrupt':target.write_bytes(b'tampered')
                else:
                    target.unlink()
                    manifest=json.loads((root/'manifest.json').read_text())
                    manifest['files'].pop(name)
                    (root/'manifest.json').write_text(json.dumps(manifest))
                with patch('verify_downloaded_artifact.subprocess.run') as run:
                    with self.assertRaises(ValueError):check(root,True)
                    run.assert_not_called()

    def test_ambiguous_download_wrapper_is_not_guessed(self):
        with tempfile.TemporaryDirectory() as d:
            root=self.package(d)
            second=Path(d)/'R3_0_Windows_Dev_second';second.mkdir()
            (second/'manifest.json').write_text('{}')
            with self.assertRaises(ValueError):package_root(d)

    def test_resource_exception_names_package_failure_not_missing_facts_or_private_path(self):
        with patch('r3studio.source_domains._EXTRACT',side_effect=FileNotFoundError('G:/private/.tld_set_snapshot')):
            with self.assertRaises(DomainResourceError) as caught:registered_domain('https://www.lge.co.kr/')
        diagnostic=caught.exception.diagnostic
        self.assertEqual(diagnostic['reason'],'PACKAGE_RESOURCE_MISSING')
        self.assertFalse(diagnostic['claims_evaluated'])
        self.assertNotIn('G:/private',str(caught.exception))
        self.assertNotIn('unverified_claims',diagnostic)

    def test_corrupt_domain_loader_is_detected_at_startup(self):
        with patch('r3studio.source_domains.registered_domain',return_value='co.kr'):
            with self.assertRaises(DomainResourceError):check_domain_resources()

    def test_workflow_checks_actual_download_after_upload_and_includes_hidden_files(self):
        text=Path('.github/workflows/windows-build.yml').read_text(encoding='utf-8')
        self.assertIn('include-hidden-files: true',text)
        self.assertIn('actions/download-artifact@v4',text)
        self.assertLess(text.index('actions/upload-artifact@v4'),text.index('actions/download-artifact@v4'))
        self.assertGreater(text.index('python verify_downloaded_artifact.py'),text.index('actions/download-artifact@v4'))
        self.assertIn('artifact_check/내려받은_시험판 --smoke-test',text)

    def test_normal_startup_checks_resources_before_constructing_app(self):
        from r3studio.startup import launch
        with tempfile.TemporaryDirectory() as d:
            factory=Mock()
            with patch('r3studio.startup.data_directory',return_value=Path(d)),patch('r3studio.source_domains.check_domain_resources',side_effect=DomainResourceError()),patch('tkinter.messagebox.showerror') as alert:
                result=launch(app_factory=factory,root_factory=Mock())
            self.assertEqual(result,1);factory.assert_not_called()
            self.assertIn('출처 판정 파일',alert.call_args.args[1])

if __name__=='__main__':unittest.main()
