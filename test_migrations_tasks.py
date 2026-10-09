import sqlite3
import tempfile
import unittest
from pathlib import Path
from r3studio.sync import Store,SCHEMA
from r3studio.tasks import Cancellation,Cancelled,TaskLog
class Tests(unittest.TestCase):
 def test_v1_migration_preserves_rows_and_backup(self):
  with tempfile.TemporaryDirectory() as d:
   path=d+'/db';db=sqlite3.connect(path);db.executescript(SCHEMA+'PRAGMA user_version=1;')
   db.execute('INSERT INTO generation_history(created_at,topic,status) VALUES(?,?,?)',('time','기존 주제','HOLD'));db.commit();db.close()
   s=Store(path)
   self.assertEqual(s.db.execute('PRAGMA user_version').fetchone()[0],2)
   self.assertEqual(s.db.execute('SELECT topic FROM generation_history').fetchone()[0],'기존 주제')
   self.assertTrue(Path(path+'.pre_v2.bak').exists());s.close()
 def test_newer_db_not_modified(self):
  with tempfile.TemporaryDirectory() as d:
   path=d+'/db';db=sqlite3.connect(path);db.execute('PRAGMA user_version=999');db.close()
   with self.assertRaises(ValueError):Store(path)
   db=sqlite3.connect(path);self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],999);db.close()
 def test_cancel_and_task_record(self):
  with tempfile.TemporaryDirectory() as d:
   s=Store(d+'/db');task=TaskLog(s,'검사');c=Cancellation();c.checkpoint();c.request()
   with self.assertRaises(Cancelled):c.checkpoint()
   task.finish('CANCELLED');self.assertEqual(s.db.execute('SELECT status FROM task_runs').fetchone()[0],'CANCELLED');s.close()
if __name__=='__main__':unittest.main()
