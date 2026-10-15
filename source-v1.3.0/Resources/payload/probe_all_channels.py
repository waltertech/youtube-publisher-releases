"""Inspect registered channels; keep untested execution bindings disabled."""
import json,threading
from concurrent.futures import ThreadPoolExecutor,as_completed
from publisher import ROOT,Ledger,datetime,TZ
from channel_probe import inspect
from onboard_windows import api
from bit_windows import fetch_all
LOCK=threading.Lock()
def run_window(w,channels):
 rows=[];was_open=bool(api('browser/pids',{'ids':[w['id']]}).get(w['id']))
 try:
  for channel in channels:
   print('核验 '+w['name']+' / '+channel['name'],flush=True)
   try:row=inspect(w,channel)
   except Exception as e:row={**channel,'intermediate_enabled':False,'error':str(e)}
   rows.append(row)
   l=Ledger();old=l.db.execute('SELECT * FROM channels WHERE id=?',(channel['id'],)).fetchone()
   if old and old['window_id']==w['id']:
    verified=bool(row.get('intermediate_enabled'));enabled=bool(old['enabled'] and verified)
    reason=row.get('error') or (row['reason']+'；运行绑定及草稿验收待完成' if verified and not enabled else row['reason'])
    l.channel(channel['id'],w['name'],channel['name'],w['id'],enabled,verified,reason)
   l.db.close()
   print(w['name']+'：'+(row.get('error') or row['reason']),flush=True)
 finally:
  if not was_open:
   try:api('browser/close',{'id':w['id']})
   except Exception:pass
 return rows
def run(window_ids=None,resume=False):
 import socket
 with socket.socket() as guard:
  try:guard.bind(('127.0.0.1',18744))
  except OSError:raise ValueError('已有频道配置或核验正在运行，请等待完成')
  l=Ledger()
  if l.db.execute("SELECT 1 FROM tasks WHERE state IN ('上传中','填写中','检查中','发布中')").fetchone():raise SystemExit('已有上传运行，请稍后核验')
  l.db.close()
  from window_scope import select_windows
  windows=select_windows(fetch_all(),window_ids);discovered=json.loads((ROOT/'窗口接入状态.json').read_text());path=ROOT/'频道权限状态.json';report=json.loads(path.read_text()) if path.exists() else {}
  with ThreadPoolExecutor(max_workers=2) as pool:
   fs={pool.submit(run_window,w,discovered[w['id']]['channels']):w for w in windows if discovered.get(w['id'],{}).get('channels') and not (resume and w['id'] in report and report[w['id']].get('channels') and not any(c.get('error') for c in report[w['id']]['channels']))}
   for f in as_completed(fs):
    w=fs[f]
    try:rows=f.result();report[w['id']]={'name':w['name'],'channels':rows,'checked_at':datetime.now(TZ).isoformat()}
    except Exception as e:report[w['id']]={'name':w['name'],'error':str(e),'channels':[]}
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2));tmp.replace(path)

  from configure_bindings import configure
  configure(window_ids)
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--resume',action='store_true');p.add_argument('--window-id',action='append');a=p.parse_args();run(a.window_id,a.resume)
