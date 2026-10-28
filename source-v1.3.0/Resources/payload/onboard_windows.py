from local_transport import urlopen as transport_urlopen
"""Read-only channel discovery. Does not upload or enable unverified channels."""
import json,time,urllib.request,argparse,socket
from publisher import ROOT,Ledger,datetime,TZ
from file_adapter import CDP
from bit_windows import fetch_all

def api(path,payload):
 req=urllib.request.Request('http://127.0.0.1:54345/'+path,json.dumps(payload).encode(),{'Content-Type':'application/json'})
 r=json.load(transport_urlopen(req,timeout=45))
 if not r.get('success'):
  if path=='browser/open' and 'ESRCH' in r.get('msg',''):
   time.sleep(1)
   r=json.load(transport_urlopen(req,timeout=45))
  if not r.get('success'):raise RuntimeError(r.get('msg','比特接口失败'))
 return r.get('data')

def discover(w):
 was_open=bool(api('browser/pids',{'ids':[w['id']]}).get(w['id']))
 d=api('browser/open',{'id':w['id']});host=d['http'];host=host if host.startswith('http') else 'http://'+host
 browser=CDP(d['ws']);tid=None
 try:
  tid=browser.call('Target.createTarget',{'url':'https://www.youtube.com/channel_switcher'})['targetId']
  end=time.time()+55
  while time.time()<end:
   tabs=json.load(transport_urlopen(host+'/json/list',timeout=8));t=next((t for t in tabs if t['id']==tid),None)
   if not t:time.sleep(1);continue
   c=CDP(t['webSocketDebuggerUrl'])
   try:
    result=c.evaluate("""({url:location.href,notice:location.pathname==='/channel-appeal'?document.body.innerText.slice(0,250):'',channels:[...document.querySelectorAll('ytd-account-item-renderer')].filter(e=>e.data?.hasChannel).map(e=>{const d=e.data;const ts=d.serviceEndpoint?.selectActiveIdentityEndpoint?.supportedTokens||[];return {id:'UC'+(ts.find(t=>t.offlineCacheKeyToken)?.offlineCacheKeyToken.clientCacheKey||''),name:d.accountName?.simpleText||e.innerText.split('\\n')[0],selected:!!d.isSelected,disabled:!!d.isDisabled,handle:d.channelHandle?.simpleText||''}})})""")
   finally:c.close()
   if result and '/channel-appeal' in result['url']:raise ValueError('YouTube 频道已被移除，无法启用发布：'+result.get('notice','').split('\n')[0])
   if result and result['channels']:
    channels=[c for c in result['channels'] if len(c['id'])==24]
    if len(channels)!=len(result['channels']):raise ValueError('频道身份数据不完整，需人工核查')
    return channels
   if result and 'accounts.google.com' in result['url']:raise ValueError('登录失效，需要在比特窗口登录 YouTube')
   time.sleep(2)
  raise ValueError('频道列表加载超时，需要检查网络、登录或验证页面')
 finally:
  if tid:browser.call('Target.closeTarget',{'targetId':tid})
  browser.close()
  if not was_open:
   try:api('browser/close',{'id':w['id']})
   except Exception:pass

def run(names=None,resume=False,window_ids=None):
 with socket.socket() as guard:
  try:guard.bind(('127.0.0.1',18742))
  except OSError:raise ValueError('已有频道配置或核验正在运行，请等待完成')
  from window_scope import select_windows
  windows=select_windows(fetch_all(),window_ids);l=Ledger();p=ROOT/'窗口接入状态.json'
  if l.db.execute("SELECT 1 FROM tasks WHERE state IN ('上传中','填写中','检查中','发布中')").fetchone():raise ValueError('已有上传正在运行，请等待完成后再检查频道')
  report=json.loads(p.read_text()) if p.exists() else {}
  for w in windows:
   if names and w['name'] not in names:continue
   if resume and report.get(w['id'],{}).get('channels'):continue
   row={**w,'checked_at':datetime.now(TZ).isoformat(),'channels':[]}
   print('检查 '+w['name'],flush=True)
   try:
    row['channels']=discover(w);row['status']='频道已发现，待核实权限和运行绑定'
    for c in row['channels']:
     old=l.db.execute('SELECT * FROM channels WHERE id=?',(c['id'],)).fetchone()
     if old and old['window_id']!=w['id']:
      c['reason']='同一频道已绑定其他窗口，保留原绑定';continue
     ready=bool(old and old['verified'] and old['enabled'] and not c.get('disabled'))
     l.channel(c['id'],w['name'],c['name'],w['id'],ready,ready,old['reason'] if ready else '已发现实际频道；长视频与封面权限、运行绑定待核实')
    print(w['name']+'：发现 '+str(len(row['channels']))+' 个频道',flush=True)
   except Exception as e:
    row['status']='待处理';row['error']=str(e);print(w['name']+'：'+str(e),flush=True)
   report[w['id']]=row
   tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(report,ensure_ascii=False,indent=2));tmp.replace(p)
  l.db.close()
  return report
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--gm',action='append');p.add_argument('--resume',action='store_true');p.add_argument('--window-id',action='append');a=p.parse_args();run(a.gm,a.resume,a.window_id)
