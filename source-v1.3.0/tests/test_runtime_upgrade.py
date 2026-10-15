import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import io
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Resources'))
import runtime_upgrade as upgrade

class UpgradeTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
 def response(self,value):return io.BytesIO(json.dumps(value).encode())
 def test_matching_version_reuses_backend(self):
  with patch.object(upgrade.urllib.request,'urlopen',return_value=self.response({'service':'ypp-dashboard','data_dir':str(self.root),'version':'1.3.1'})):
   self.assertTrue(upgrade.ensure_current_service(self.root,19741,'http://localhost:19741','1.3.1'))
 def test_old_idle_backend_is_backed_up_and_terminated(self):
  with patch.object(upgrade.urllib.request,'urlopen',side_effect=[self.response({'service':'ypp-dashboard','data_dir':str(self.root)}),self.response({'tasks':[],'job':{'running':False}})]),patch.object(upgrade.update_install,'services',return_value=[123]),patch.object(upgrade.update_install,'backup') as backup,patch.object(upgrade.update_install,'terminate') as stop:
   self.assertFalse(upgrade.ensure_current_service(self.root,19741,'http://localhost:19741','1.3.1'));backup.assert_called_once();stop.assert_called_once_with([123])
  self.assertFalse((self.root/'.update-lock').exists())
 def test_active_upload_or_operation_is_never_terminated(self):
  for status in [{'tasks':[{'state':'上传中'}]}, {'tasks':[],'job':{'running':True}}]:
   with patch.object(upgrade.urllib.request,'urlopen',side_effect=[self.response({'service':'ypp-dashboard','data_dir':str(self.root)}),self.response(status)]),patch.object(upgrade.update_install,'terminate') as stop:
    with self.assertRaisesRegex(ValueError,'已保留原任务'):upgrade.ensure_current_service(self.root,19741,'http://localhost:19741','1.3.1')
    stop.assert_not_called()
   self.assertFalse((self.root/'.update-lock').exists())
 def test_other_data_directory_is_not_terminated(self):
  with patch.object(upgrade.urllib.request,'urlopen',return_value=self.response({'service':'ypp-dashboard','data_dir':'/other/path'})),patch.object(upgrade.update_install,'terminate') as stop:
   with self.assertRaisesRegex(ValueError,'另一数据目录'):upgrade.ensure_current_service(self.root,19741,'http://localhost:19741','1.3.1')
   stop.assert_not_called()
 def test_no_process_identity_is_not_terminated(self):
  with patch.object(upgrade.urllib.request,'urlopen',side_effect=[self.response({'service':'ypp-dashboard','data_dir':str(self.root)}),self.response({'tasks':[]})]),patch.object(upgrade.update_install,'services',return_value=[]),patch.object(upgrade.update_install,'terminate') as stop:
   with self.assertRaisesRegex(ValueError,'进程身份'):upgrade.ensure_current_service(self.root,19741,'http://localhost:19741','1.3.1')
   stop.assert_not_called()
