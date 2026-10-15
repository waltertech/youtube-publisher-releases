import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Resources/payload'))
import scan_materials as scan
import material_rules
from publisher import Ledger
from window_scope import select_windows

class FallbackTests(unittest.TestCase):
 def test_fallback_only_when_both_sources_empty(self):
  p=scan.parse_copy('发布标题\nTitle\n详情内容\nYouTube Studio Tags\na,b\nHashtags\n','Fallback\nSecond')
  self.assertEqual((p['description'],p['raw_description'],p['hashtags'],p['description_source']),('Fallback\nSecond','','','兜底配置'))
  for text,expected in [('body\n#Inside','body\n#Inside'),('','#Only')]:
   p=scan.parse_copy('发布标题\nTitle\n详情内容\n'+text+'\nYouTube Studio Tags\n\nHashtags\n#Only','Fallback')
   self.assertEqual(p['description'],expected)
 def test_empty_or_invalid_fallback(self):
  with self.assertRaises(ValueError):material_rules.validate({**material_rules.DEFAULTS,'fallback_description':'a'*5001})
  self.assertEqual(material_rules.validate({'copy_keywords':['文案'],'cover_keywords':['封面']})['fallback_description'],'')
 def test_lightweight_refresh_preserves_assigned_tasks_and_never_hashes_video(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);(root/'a.mp4').write_bytes(b'one');(root/'b.mp4').write_bytes(b'two');(root/'封面.jpg').write_bytes(b'image');(root/'文案.txt').write_text('text')
   items=[{'video':str(root/n),'thumbnail':str(root/'封面.jpg'),'copy_file':str(root/'文案.txt'),'title':'title','description':'','hashtags':'','raw_description':'','description_source':'空'} for n in ['a.mp4','b.mp4']]
   l=Ledger(root/'ledger.sqlite3')
   try:
    with contextlib.redirect_stdout(io.StringIO()):l.scan(items)
    l.channel('UC1','GM001','one',enabled=True,verified=True)
    sha=l.db.execute('SELECT sha FROM assets ORDER BY sha LIMIT 1').fetchone()[0]
    l.db.execute("INSERT INTO tasks(id,channel,day,sha,state) VALUES('task','UC1','2026-10-15',?,'待执行')",(sha,))
    new=[{**i,'description':'fallback','description_source':'兜底配置'} for i in items]
    with patch('publisher.hashlib.sha256',side_effect=AssertionError('must not hash')),contextlib.redirect_stdout(io.StringIO()):self.assertEqual(l.refresh_materials(new),1)
    assigned=json.loads(l.db.execute('SELECT payload FROM assets WHERE sha=?',(sha,)).fetchone()[0]);self.assertEqual(assigned['description'],'')
    self.assertEqual(l.db.execute('SELECT count(*) FROM assets WHERE complete=1').fetchone()[0],1)
   finally:l.db.close()

class ScopeTests(unittest.TestCase):
 def test_scope_uses_ids_even_when_names_are_identical(self):
  windows=[{'id':'one','name':'same'},{'id':'two','name':'same'}]
  self.assertEqual(select_windows(windows,['two']),[windows[1]])
  self.assertEqual(select_windows(windows,None),windows)
  for bad in [[],['missing']]:
   with self.assertRaises(ValueError):select_windows(windows,bad)
 def test_initialization_passes_scope_to_both_stages(self):
  import installation
  windows=[{'id':'one','name':'same'},{'id':'two','name':'same'}]
  with patch.object(installation,'fetch_all',return_value=windows),patch.object(installation.subprocess,'run') as run,patch.object(installation,'window_result',return_value=(1,'')),contextlib.redirect_stdout(io.StringIO()):
   installation.initialize(['two'])
   self.assertEqual(run.call_count,2)
   for call in run.call_args_list:self.assertEqual(call.args[0][-2:],['--window-id','two'])
 def test_partial_binding_keeps_unselected_channel_and_readiness(self):
  import configure_bindings as binding
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);db=root/'ledger.sqlite3';l=Ledger(db)
   l.channel('UC1','GM001','one','one',False,False,'old1');l.channel('UC2','GM002','two','two',False,False,'untouched');before=dict(l.db.execute("SELECT * FROM channels WHERE id='UC2'").fetchone());l.db.close()
   (root/'调度配置.json').write_text(json.dumps({'execution_engine':'local','direct_public_approved':True,'manual_ready':{'GM002':False}}))
   reports={wid:{'name':name,'channels':[{'id':cid,'name':name,'intermediate_enabled':True,'language':'en','reason':'ok'}]} for wid,name,cid in [('one','GM001','UC1'),('two','GM002','UC2')]}
   (root/'频道权限状态.json').write_text(json.dumps(reports))
   with patch.object(binding,'ROOT',root),patch.object(binding,'Ledger',side_effect=lambda:Ledger(db)),contextlib.redirect_stdout(io.StringIO()):binding.configure(['one'])
   l=Ledger(db)
   try:
    self.assertEqual(dict(l.db.execute("SELECT * FROM channels WHERE id='UC2'").fetchone()),before)
    self.assertEqual(l.db.execute("SELECT enabled FROM channels WHERE id='UC1'").fetchone()[0],1)
   finally:l.db.close()
   self.assertFalse(json.loads((root/'调度配置.json').read_text())['manual_ready']['GM002'])
 def test_discovery_never_opens_unselected_windows(self):
  import onboard_windows as onboard
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);db=root/'ledger.sqlite3';windows=[{'id':'one','name':'same'},{'id':'two','name':'same'}]
   with patch.object(onboard,'ROOT',root),patch.object(onboard,'Ledger',side_effect=lambda:Ledger(db)),patch.object(onboard,'fetch_all',return_value=windows),patch.object(onboard,'discover',return_value=[]) as discover,contextlib.redirect_stdout(io.StringIO()):
    onboard.run(window_ids=['two']);discover.assert_called_once_with(windows[1])
 def test_permission_stage_never_probes_unselected_windows(self):
  import probe_all_channels as probe
  import configure_bindings
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);db=root/'ledger.sqlite3';windows=[{'id':'one','name':'same'},{'id':'two','name':'same'}]
   reports={w['id']:{'name':'same','channels':[{'id':'UC'+w['id'],'name':'channel'}]} for w in windows}
   (root/'窗口接入状态.json').write_text(json.dumps(reports));old={'one':{'name':'same','channels':[{'id':'old'}]}};(root/'频道权限状态.json').write_text(json.dumps(old))
   with patch.object(probe,'ROOT',root),patch.object(probe,'Ledger',side_effect=lambda:Ledger(db)),patch.object(probe,'fetch_all',return_value=windows),patch.object(probe,'run_window',return_value=[]) as run,patch.object(configure_bindings,'configure') as configure:
    probe.run(['two']);self.assertEqual(run.call_count,1);self.assertEqual(run.call_args.args[0]['id'],'two');configure.assert_called_once_with(['two'])
   self.assertEqual(json.loads((root/'频道权限状态.json').read_text())['one'],old['one'])
