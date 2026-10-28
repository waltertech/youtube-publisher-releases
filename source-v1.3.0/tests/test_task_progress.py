import sys,unittest,threading
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Resources/payload'))
import task_progress as p
class ProgressTests(unittest.TestCase):
 def test_processing_is_not_upload(self):
  self.assertEqual(p.parse_progress({'text':'Processing 60%\nUploading 12% ... 3 minutes left'})[0],12)
  self.assertIsNone(p.parse_progress({'text':'Processing 60%'})[0])
 def test_ambiguous_progress_rejected(self):
  with self.assertRaises(ValueError):p.parse_progress({'text':'Uploading 12%\nUploading 90%'})
 def test_chinese_and_status_scope(self):
  self.assertEqual(p.parse_progress({'status':'正在上传 45%','text':'Uploading 90%'})[0],45)
 def test_fast_task_does_not_wait_for_slow_one(self):
  release=threading.Event();published=[]
  def observe(t):
   if t['id']=='slow':
    if not release.wait(2):raise AssertionError('fast task was blocked')
   return {'task':t['id'],'percent':12 if t['id']=='slow' else 83}
  def publish(r):published.append(r);release.set()
  with patch.object(p,'observe',side_effect=observe):p.collect([{'id':'slow'},{'id':'fast'}],publish)
  self.assertEqual(published,[{'task':'fast','percent':83},{'task':'slow','percent':12}])
