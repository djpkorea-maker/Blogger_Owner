import sqlite3
import tempfile
import unittest
from pathlib import Path
from r3studio.backups import snapshot,inventory,inventory_text
class Tests(unittest.TestCase):
 def test_backup_inventory_reads_counts_and_rejects_corruption(self):
  with tempfile.TemporaryDirectory() as d:
   base=Path(d);folder=base/'backups';folder.mkdir()
   db=sqlite3.connect(folder/'studio_20261009.sqlite3');db.execute('CREATE TABLE posts(value)');db.execute('INSERT INTO posts VALUES(1)');db.commit();db.close()
   (folder/'studio_20261008.sqlite3').write_bytes(b'not sqlite')
   items=inventory(base);self.assertTrue(items[0]['valid']);self.assertEqual(items[0]['counts']['posts'],1);self.assertFalse(items[1]['valid'])
   self.assertIn('원본 DB를 변경하거나 복원하지 않습니다',inventory_text(items))
 def test_snapshot_preserves_earlier_records_and_is_daily(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'studio.sqlite3';db=sqlite3.connect(path);db.execute('CREATE TABLE record(value)');db.execute('INSERT INTO record VALUES(?)',('기록1',));db.commit()
   saved=snapshot(path,Path(d)/'backups',day='20261009')
   db.execute('INSERT INTO record VALUES(?)',('기록2',));db.commit()
   self.assertEqual(snapshot(path,Path(d)/'backups',day='20261009'),saved)
   old=sqlite3.connect(saved);self.assertEqual(old.execute('SELECT count(*) FROM record').fetchone()[0],1);old.close();db.close()
 def test_missing_database_does_not_create_one(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'missing.sqlite3';self.assertIsNone(snapshot(path,Path(d)/'backups'));self.assertFalse(path.exists())
 def test_retention_keeps_latest_seven(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'studio.sqlite3';db=sqlite3.connect(path);db.execute('CREATE TABLE record(value)');db.commit();db.close()
   folder=Path(d)/'backups'
   for day in range(1,10):snapshot(path,folder,day=f'202610{day:02}')
   self.assertEqual(len(list(folder.glob('*.sqlite3'))),7);self.assertFalse((folder/'studio_20261001.sqlite3').exists())
if __name__=='__main__':unittest.main()
