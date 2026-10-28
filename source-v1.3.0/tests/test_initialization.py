import contextlib,io,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Resources/payload'))
import installation,bit_windows
class InitializationTests(unittest.TestCase):
 def test_each_window_is_completed_before_next_and_failure_continues(self):
  windows=[{'id':'one','name':'GM040'},{'id':'two','name':'GM041'}]
  with tempfile.TemporaryDirectory() as t,patch.object(installation,'ROOT',Path(t)),patch.object(installation,'fetch_all',return_value=windows),patch.object(installation.subprocess,'run') as run,patch.object(installation,'window_result',side_effect=[(0,'登录失效'),(1,'')]),contextlib.redirect_stdout(io.StringIO()) as out:
   installation.initialize()
   self.assertEqual([(Path(c.args[0][2]).name,c.args[0][-1]) for c in run.call_args_list],[('onboard_windows.py','one'),('probe_all_channels.py','one'),('onboard_windows.py','two'),('probe_all_channels.py','two')])
   self.assertIn('1/2 个窗口可用',out.getvalue())
 def test_all_failed_is_failure(self):
  with tempfile.TemporaryDirectory() as t,patch.object(installation,'ROOT',Path(t)),patch.object(installation,'fetch_all',return_value=[{'id':'one','name':'GM040'}]),patch.object(installation.subprocess,'run'),patch.object(installation,'window_result',return_value=(0,'手机号未验证')),contextlib.redirect_stdout(io.StringIO()):
   with self.assertRaisesRegex(ValueError,'手机号未验证'):installation.initialize()
 def test_empty_account_is_explicit(self):
  with patch.object(installation,'fetch_all',return_value=[]):
   with self.assertRaisesRegex(ValueError,'没有返回窗口'):installation.initialize()
 def test_api_reason_reaches_cache(self):
  reply=io.BytesIO(json.dumps({'success':False,'msg':'Local API disabled'}).encode())
  with patch.object(bit_windows.LOCAL_OPENER,'open',return_value=reply),patch.object(bit_windows,'CACHE',{'items':[],'updated':None,'error':''}):
   with self.assertRaisesRegex(ValueError,'Local API disabled'):bit_windows.refresh()
   self.assertIn('Local API disabled',bit_windows.state()['error'])
 def test_discovery_failure_skips_stale_permissions(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);(root/'窗口接入状态.json').write_text(json.dumps({'one':{'error':'频道列表加载超时'}}))
   with patch.object(installation,'ROOT',root),patch.object(installation,'fetch_all',return_value=[{'id':'one','name':'GM040'}]),patch.object(installation.subprocess,'run') as run,contextlib.redirect_stdout(io.StringIO()):
    with self.assertRaisesRegex(ValueError,'频道列表加载超时'):installation.initialize()
    self.assertEqual(run.call_count,1)
