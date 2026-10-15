"""Bind verified profiles to the local BitBrowser runner. Public remains gated."""
import json
from publisher import ROOT,Ledger

def configure(window_ids=None):
 p=ROOT/'频道权限状态.json';reports=json.loads(p.read_text()) if p.exists() else {}
 l=Ledger();path=ROOT/'调度配置.json';cfg=json.loads(path.read_text())
 cfg['execution_engine']='local'
 from acceptance import fingerprint
 if not cfg.get('direct_public_approved') and cfg.get('accepted_runner')!=fingerprint():cfg['local_public_enabled']=False
 ready=dict(cfg.get('manual_ready',{})) if window_ids is not None else {};count=0
 for window_id,report in reports.items():
  if window_ids is not None and window_id not in window_ids:continue
  gm=report['name'];ready[gm]=False
  for ch in report.get('channels',[]):
   old=l.db.execute('SELECT * FROM channels WHERE id=?',(ch['id'],)).fetchone()
   if not old or old['window_id']!=window_id:continue
   permission=bool(ch.get('intermediate_enabled'));language=ch.get('language','');supported=language.startswith(('en','zh'))
   enabled=permission and supported and not ch.get('error')
   reason=ch.get('error') or ('已接入本机执行器；可手动草稿，完整草稿验收前不开放正式发布' if enabled else '界面语言 '+language+' 尚未通过上传适配，请切换为英文或简体中文后重新核验' if permission else ch.get('reason','权限未核实'))
   if (old['gm'],old['name'],old['enabled'],old['verified'],old['reason'])!=(gm,ch['name'],int(enabled),int(permission),reason):l.channel(ch['id'],gm,ch['name'],window_id,enabled,permission,reason)
   ready[gm]=ready[gm] or enabled;count+=int(enabled)
 if window_ids is not None:
  names={report['name'] for wid,report in reports.items() if wid in window_ids}
  for gm in names:
   ready[gm]=bool(l.db.execute('SELECT 1 FROM channels WHERE gm=? AND enabled=1 AND verified=1',(gm,)).fetchone())
 cfg['manual_ready']=ready
 tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(cfg,ensure_ascii=False,indent=2));tmp.replace(path)
 l.db.close();print('本机绑定完成：'+str(sum(ready.values()))+' 个窗口，'+str(count)+' 个可用频道；正式发布待完整草稿验收。',flush=True)
if __name__=='__main__':configure()
