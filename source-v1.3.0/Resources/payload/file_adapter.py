from local_transport import websocket_options
from local_transport import urlopen as transport_urlopen
"""BitBrowser RPA large-file upload adapter; task-bound, no file streaming."""
import json,urllib.request,time
from pathlib import Path
from websockets.sync.client import connect
from publisher import Ledger,ROOT,datetime,TZ

class CDP:
 def __init__(self,ws):self.ws=connect(ws,**websocket_options(ws),origin=None,max_size=8*1024*1024,open_timeout=10);self.seq=0
 def call(self,method,params=None):
  self.seq+=1;key=self.seq;self.ws.send(json.dumps({'id':key,'method':method,'params':params or {}}))
  while True:
   x=json.loads(self.ws.recv(timeout=30))
   if x.get('id')==key:
    if 'error' in x:raise RuntimeError(x['error']['message'])
    return x.get('result',{})
 def evaluate(self,code):
  r=self.call('Runtime.evaluate',{'expression':code,'returnByValue':True,'awaitPromise':True})
  if r.get('exceptionDetails'):raise RuntimeError(r['exceptionDetails'].get('text','页面脚本错误'))
  return r.get('result',{}).get('value')
 def close(self):self.ws.close()

def active_task(p):
 from parallel_settings import task_path
 path=task_path(p.get('key',''))
 a=json.loads((path if path.exists() else ROOT/'.active-task.json').read_text());l=Ledger()
 t=l.db.execute('SELECT * FROM tasks WHERE id=?',(a['id'],)).fetchone()
 if not t or p.get('key')!=a['id'] or p.get('token')!=t['token'] or a['token']!=t['token']:raise ValueError('无效任务凭据')
 if p.get('channel_id')!=t['channel'] or a['channel_id']!=t['channel']:raise ValueError('频道不匹配')
 return a,l,t

def page(a,require_dialog=True):
 req=urllib.request.Request('http://127.0.0.1:54345/browser/open',json.dumps({'id':a['window_id']}).encode(),{'Content-Type':'application/json'})
 result=json.load(transport_urlopen(req,timeout=20))
 if not result.get('success'):raise ValueError('无法连接目标GM窗口')
 host=result['data']['http'];host=host if host.startswith('http') else 'http://'+host
 tabs=json.load(transport_urlopen(host+'/json/list',timeout=10))
 candidates=[x for x in tabs if (not a.get('target_id') or x.get('id')==a['target_id']) and x.get('type')=='page' and x.get('url','').startswith('https://studio.youtube.com/channel/'+a['channel_id'])]
 # Prefer upload dialog, but reject multiple upload targets.
 opened=[]
 for x in candidates:
  c=CDP(x['webSocketDebuggerUrl'])
  v=c.evaluate("({channel:document.querySelector('a[href*=\"studio.youtube.com/channel/\"]')?.href||[...document.querySelectorAll('a[href]')].map(x=>x.href).find(x=>/^https:\\/\\/studio.youtube.com\\/channel\\/UC/.test(x)),published:/Video published|视频已发布/i.test(document.body.innerText),dialog:!!document.querySelector('ytcp-uploads-dialog')})")
  if v and v.get('channel','').split('/channel/')[-1].split('/')[0]==a['channel_id'] and (v.get('dialog') if require_dialog else v.get('published')):opened.append(c);c.monitor_ws=x['webSocketDebuggerUrl']
  else:c.close()
 if len(opened)!=1:
  for c in opened:c.close()
  raise ValueError('需要唯一且频道身份正确的上传对话框')
 import os
 from parallel_settings import task_path
 monitor=task_path(a['id'],'monitor')
 fd=os.open(monitor,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
 with os.fdopen(fd,'w') as f:json.dump({'task':a['id'],'channel':a['channel_id'],'ws':opened[0].monitor_ws},f)
 return opened[0]

def upload(p,now=None):
 a,l,t=active_task(p);kind=p.get('kind')
 if kind not in ('video','thumbnail'):raise ValueError('不支持的文件类型')
 if kind=='video' and not ('manual' in t.keys() and t['manual']):
  from schedule_settings import read,in_window
  setting=read()
  if not setting['enabled'] or a['window_id'] not in setting['window_ids'] or not in_window(now or datetime.now(TZ),setting):raise ValueError('定时调度已关闭、窗口已取消或已超过启动时段')
 expected='上传中' if kind=='video' else '填写中'
 if t['state']!=expected:raise ValueError('任务阶段不允许上传文件')
 path=Path(a[kind]).resolve()
 if not path.is_file():raise ValueError('素材文件不存在')
 if kind=='video' and (path.stat().st_size!=a['video_size'] or path.stat().st_mtime_ns!=a['video_mtime_ns']):raise ValueError('视频文件在分配后发生变化')
 l.db.execute('CREATE TABLE IF NOT EXISTS file_submissions(task TEXT,kind TEXT,state TEXT,PRIMARY KEY(task,kind))')
 if l.db.execute('SELECT 1 FROM file_submissions WHERE task=? AND kind=?',(a['id'],kind)).fetchone():raise ValueError('文件已提交或提交结果待核查，禁止重复上传')
 c=page(a)
 try:
  selector='ytcp-uploads-file-picker input[type=file]' if kind=='video' else 'ytcp-video-thumbnail-editor input[type=file]'
  r=c.call('Runtime.evaluate',{'expression':'document.querySelector('+json.dumps(selector)+')'})['result']
  if not r.get('objectId') or r.get('subtype')=='null':raise ValueError('没有找到目标文件选择控件')
  with l.tx():l.db.execute('INSERT INTO file_submissions VALUES(?,?,?)',(a['id'],kind,'提交中'))
  c.call('DOM.setFileInputFiles',{'files':[str(path)],'objectId':r['objectId']})
  l.db.execute('UPDATE file_submissions SET state=? WHERE task=? AND kind=?',('已提交',a['id'],kind))
  return {'ok':True,'kind':kind,'bytes':path.stat().st_size}
 finally:c.close()

def validate_draft_evidence(evidence,reviewed=False):
 text=evidence['text'];links=evidence['links']
 import re
 if re.search(r'Uploading\s*\d|Uploading video|上传中|上传失败|Upload failed',text,re.I):raise ValueError('上传尚未完成或出现错误')
 if not re.search(r'Saved as private|保存为私享|已保存为私享',text,re.I):raise ValueError('没有确认草稿已保存为私密')
 if not re.search(r'Checks complete|检查完成|检查完毕',text,re.I):raise ValueError('平台检查尚未完成')
 if not reviewed and re.search(r'Copyright claim|Copyright-protected content found|Claimed content found|发现版权声明|版权声明|发现受版权保护',text,re.I):raise ValueError('平台检查发现版权异常，需要人工核查')
 url=next((u for u in links if re.match(r'https://youtu\.be/[\w-]{11}$',u)),None)
 if not url:raise ValueError('未取得准确的视频ID')
 return url

def confirm_draft(p):
 a,l,t=active_task(p)
 if t['state'] not in ('检查中','结果待核查'):raise ValueError('当前任务阶段不能确认草稿')
 c=page(a)
 try:
  evidence=c.evaluate("({text:document.querySelector('ytcp-uploads-dialog')?.innerText||'',links:[...document.querySelectorAll('ytcp-uploads-dialog a[href]')].map(a=>a.href)})")
 finally:c.close()
 from review_task import approved
 url=validate_draft_evidence(evidence,reviewed=any(approved(a,u) for u in evidence['links']))
 now=datetime.now(TZ).isoformat()
 import uuid
 with l.tx():
  current=l.db.execute('SELECT state,token FROM tasks WHERE id=?',(a['id'],)).fetchone()
  if current['token']!=a['token'] or current['state'] not in ('检查中','结果待核查'):raise ValueError('任务状态已改变')
  l.db.execute("UPDATE tasks SET state='草稿',url=?,error='' WHERE id=?",(url,a['id']));l.queue('tasks',a['id'])
  key=uuid.uuid4().hex;l.db.execute('INSERT INTO logs VALUES(?,?,?,?,?,?,?,?)',(key,a['id'],'草稿确认',now,now,'','','已验证上传结束、平台检查完成、Saved as private及视频ID'));l.queue('logs',key)
 return {'ok':True,'state':'草稿','url':url}


def prepare_publish(p):
 a,l,t=active_task(p)
 if t['mode']!='public' or t['state']!='检查中':raise ValueError('此任务未选择正式发布，或尚未检查完成')
 c=page(a)
 try:e=c.evaluate("({text:document.querySelector('ytcp-uploads-dialog')?.innerText||'',links:[...document.querySelectorAll('ytcp-uploads-dialog a[href]')].map(a=>a.href)})")
 finally:c.close()
 from review_task import approved
 url=validate_draft_evidence(e,reviewed=any(approved(a,u) for u in e['links']))
 l.report(a['id'],a['token'],'发布中',a['channel_id'],url=url)
 return {'ok':True,'url':url}

def confirm_public(p):
 a,l,t=active_task(p)
 if t['mode']!='public' or t['state']!='发布中':raise ValueError('此任务不在正式发布阶段')
 c=page(a,require_dialog=False)
 try:e=c.evaluate("({text:document.body.innerText,links:[...document.querySelectorAll('a[href]')].map(a=>a.href)})")
 finally:c.close()
 import re
 if not re.search(r'Video published|视频已发布',e['text'],re.I):raise ValueError('尚未取得平台发布成功证据，禁止重传')
 expected=t['url']
 if not expected or expected not in e['links']:raise ValueError('发布成功页面的视频ID不匹配')
 if p.get('public_selected') is not True:raise ValueError('缺少公开可见性核对证据')
 l.report(a['id'],a['token'],'已发布',a['channel_id'],url=expected,video_id=expected.rsplit('/',1)[-1],public=True)
 return {'ok':True,'url':expected}
