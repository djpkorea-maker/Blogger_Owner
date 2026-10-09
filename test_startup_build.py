import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import build_windows
from r3studio.startup import InstanceLock,AlreadyRunning,record_failure,launch

class Root:
 def __init__(self):self.closed=False
 def mainloop(self):pass
 def destroy(self):self.closed=True

class Tests(unittest.TestCase):
 def test_lock_blocks_second_instance_and_releases(self):
  with tempfile.TemporaryDirectory() as d:
   first=InstanceLock(Path(d)/'lock').acquire()
   try:
    with self.assertRaises(AlreadyRunning):InstanceLock(Path(d)/'lock').acquire()
   finally:first.release()
   second=InstanceLock(Path(d)/'lock').acquire();second.release()
 def test_failure_log_excludes_exception_and_source_text(self):
  with tempfile.TemporaryDirectory() as d:
   try:raise ValueError('api_key=secret')
   except ValueError as error:path=record_failure(d,error)
   text=path.read_text();self.assertNotIn('secret',text);self.assertNotIn('api_key',text)
   self.assertEqual(json.loads(text)['error_type'],'ValueError')
 def test_start_failure_records_and_releases_lock(self):
  with tempfile.TemporaryDirectory() as d:
   root=Root()
   def broken(root):raise RuntimeError('private payload')
   with patch('r3studio.startup.data_directory',return_value=Path(d)),patch('tkinter.messagebox.showerror') as alert:
    self.assertEqual(launch(app_factory=broken,root_factory=lambda:root),1);alert.assert_called_once()
   self.assertTrue(root.closed)
   lock=InstanceLock(Path(d)/'studio.lock').acquire();lock.release()
   self.assertNotIn('private', (Path(d)/'diagnostics/errors.jsonl').read_text())
 def test_normal_and_diagnostic_build_are_separate(self):
  normal,diagnostic=build_windows.build_commands('python')
  self.assertIn('--windowed',normal);self.assertIn('--console',diagnostic)
  self.assertTrue(normal[-1].endswith('desktop_entry.py'));self.assertTrue(diagnostic[-1].endswith('diagnose.py'))
 def test_tk_start_failure_keeps_diagnostics_without_second_crash(self):
  import tkinter as tk
  with tempfile.TemporaryDirectory() as d:
   with patch('r3studio.startup.data_directory',return_value=Path(d)),patch('tkinter.messagebox.showerror',side_effect=tk.TclError('no display')):
    self.assertEqual(launch(root_factory=lambda:(_ for _ in ()).throw(tk.TclError('private display error'))),1)
   self.assertEqual(json.loads((Path(d)/'diagnostics/errors.jsonl').read_text())['error_type'],'TclError')
 def test_bundle_contains_only_explicit_build_outputs(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)
   for name in ('R3_Blogger_Studio','R3_Blogger_Diagnostics'):
    p=root/'dist'/name;p.mkdir(parents=True);(p/(name+'.exe')).write_bytes(b'mock-exe')
   for name in ('QUICK_START_KO.md','WINDOWS_VALIDATION.md'):(root/name).write_text('guide')
   (root/'settings.json').write_text('secret');(root/'studio.sqlite3').write_bytes(b'private')
   release=root/'release'/'test';release.mkdir(parents=True)
   with patch.object(build_windows,'ROOT',root):target=build_windows.bundle(release)
   import zipfile
   with zipfile.ZipFile(target) as archive:
    names=archive.namelist();self.assertFalse(any('settings' in n or 'sqlite' in n for n in names))
   manifest=json.loads((release/'manifest.json').read_text())
   self.assertEqual(manifest['status'],'WINDOWS_BUILD_UNVERIFIED');self.assertEqual(len(manifest['files']),4)
 def test_bundle_rejects_missing_exe_and_private_files_before_copy(self):
  for failure in ('missing_exe','empty_exe','private_file','dirty_destination'):
   with self.subTest(failure=failure),tempfile.TemporaryDirectory() as d:
    root=Path(d)
    for name in ('R3_Blogger_Studio','R3_Blogger_Diagnostics'):
     p=root/'dist'/name;p.mkdir(parents=True);(p/(name+'.exe')).write_bytes(b'mock-exe')
    for name in ('QUICK_START_KO.md','WINDOWS_VALIDATION.md'):(root/name).write_text('guide')
    normal=root/'dist/R3_Blogger_Studio';exe=normal/'R3_Blogger_Studio.exe'
    release=root/'release/test';release.mkdir(parents=True)
    if failure=='missing_exe':exe.unlink()
    elif failure=='empty_exe':exe.write_bytes(b'')
    elif failure=='private_file':(normal/'settings.json').write_text('private')
    else:(release/'existing.txt').write_text('keep')
    with patch.object(build_windows,'ROOT',root),self.assertRaises(RuntimeError):build_windows.bundle(release)
    self.assertFalse((release/'Studio').exists());self.assertFalse(release.with_suffix('.zip').exists())
if __name__=='__main__':unittest.main()
