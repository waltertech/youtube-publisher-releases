from local_transport import urlopen as transport_urlopen
"""Loopback bridge for native Bit RPA. Credentials never sync to Feishu."""
import json,secrets,os,urllib.request,argparse,time
from http.server import HTTPServer,BaseHTTPRequestHandler
from publisher import ROOT,Ledger
SECRET=ROOT/'.bridge-secret'
if not SECRET.exists():SECRET.write_text(secrets.token_hex(32));os.chmod(SECRET,0o600)
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  if self.path=='/health' and self.headers.get('X-Publisher-Key')==SECRET.read_text():return self.reply(200,{'service':'ypp-bridge'})
  self.reply(404,{'error':'无效路径'})
 def reply(self,code,data):
  print('RPA bridge',self.path,code,flush=True)
  self.send_response(code);self.send_header('Content-Type','application/json');self.send_header('Access-Control-Allow-Origin','*');self.end_headers();self.wfile.write(json.dumps(data,ensure_ascii=False).encode())
 def do_OPTIONS(self):
  self.send_response(204);self.send_header('Access-Control-Allow-Origin','*');self.send_header('Access-Control-Allow-Methods','POST, OPTIONS');self.send_header('Access-Control-Allow-Headers','Content-Type, X-Publisher-Key');self.end_headers()
 def do_POST(self):
  if self.headers.get('X-Publisher-Key')!=SECRET.read_text():return self.reply(403,{'error':'拒绝访问'})
  try:
   size=int(self.headers.get('Content-Length','0'))
   if size>65536:raise ValueError('请求过大')
   p=json.loads(self.rfile.read(size));l=Ledger()
   if self.path=='/input':
    active=json.loads((ROOT/'.active-task.json').read_text())
    if p['gm']!=active['gm']:raise ValueError('GM窗口不匹配')
    t=l.db.execute('SELECT state,token FROM tasks WHERE id=?',(active['id'],)).fetchone()
    if not t or t['token']!=active['token'] or t['state']!='上传中':raise ValueError('没有有效已领取任务')
    self.reply(200,active)
   elif self.path=='/upload-file':
    from file_adapter import upload
    self.reply(200,upload(p))
   elif self.path=='/prepare-publish':
    from file_adapter import prepare_publish
    self.reply(200,prepare_publish(p))
   elif self.path=='/confirm-public':
    from file_adapter import confirm_public
    self.reply(200,confirm_public(p))
   elif self.path=='/confirm-draft':
    from file_adapter import confirm_draft
    self.reply(200,confirm_draft(p))
   elif self.path=='/template':
    self.reply(200,json.loads((ROOT/'YouTube多频道发布-通用草稿.automa.json').read_text()))
   elif self.path=='/probe':
    active=json.loads((ROOT/'.active-task.json').read_text())
    if p.get('key')!=active['id'] or p.get('token')!=active['token']:raise ValueError('诊断任务不匹配')
    q=ROOT/'.probe-result.json';q.write_text(json.dumps(p.get('probe',{}),ensure_ascii=False,indent=2));os.chmod(q,0o600);self.reply(200,{'ok':True})
   elif self.path=='/report':l.report(**p);self.reply(200,{'ok':True})
   else:self.reply(404,{'error':'无效路径'})
  except Exception as e:self.reply(409,{'error':str(e)})
def dispatch(gms=None,manual=False,mode="draft",task_ids=None):
 if (ROOT/'.update-lock').exists():raise ValueError('正在安装应用更新，已暂停新任务')
 import socket
 from contextlib import ExitStack
 with ExitStack() as stack:
  for port in (18742,18744):
   probe=stack.enter_context(socket.socket())
   try:probe.bind(('127.0.0.1',port))
   except OSError:raise ValueError('正在核查窗口和频道，请等待接入检查结束后再启动上传')
  import parallel_settings
  limit=parallel_settings.read();started=0
  config=json.loads((ROOT/'调度配置.json').read_text())
  if config.get('execution_engine')!='local':limit=1
  for _ in range(limit):
   try:_dispatch(gms,manual,mode,task_ids);started+=1
   except ValueError:
    if not started:raise
    break
  print('本次已启动 '+str(started)+' 条任务；并行上限 '+str(limit),flush=True)
  return started

def _dispatch(gms=None,manual=False,mode="draft",task_ids=None):
 c=json.loads((ROOT/'调度配置.json').read_text());l=Ledger()
 schedule=None
 if not manual:
  import schedule_settings
  schedule=schedule_settings.read()
  if not schedule['enabled']:raise ValueError('定时调度已关闭')
  blocked=schedule_settings.blockers(c,schedule)
  if blocked:raise ValueError('；'.join(blocked))
  if mode!=schedule['mode']:raise ValueError('定时发布类型已变化，取消本次启动')
  if not schedule_settings.in_window(__import__('datetime').datetime.now(__import__('publisher').TZ),schedule):raise ValueError('当前不在定时执行时段')
  allowed={r['gm'] for r in l.db.execute('SELECT gm,window_id FROM channels') if r['window_id'] in schedule['window_ids']}
  gms=[g for g in (gms or []) if g in allowed]
  if not gms:raise ValueError('没有符合定时设置的窗口')
 # Require only one GM per native task; UI binding must be verified before setting this flag.
 if not manual and c.get('execution_engine')!='local' and not c.get('bindings_verified'):raise ValueError('原生RPA任务窗口绑定未核实')
 if mode not in ('draft','public'):raise ValueError('发布类型无效')
 if c.get('execution_engine')=='local' and mode=='public' and not c.get('local_public_enabled'):raise ValueError('本机通用执行器尚未完成完整草稿验收，正式发布暂未启用')
 if not manual and mode=='public' and not c.get('public_enabled'):raise ValueError('定时公开发布未启用')
 if manual:
  ready=c.get('manual_ready',{})
  eligible=[g for g in (gms or []) if ready.get(g) and (c.get('execution_engine')=='local' or c.get('native_tasks',{}).get(g))]
  skipped=sorted(set(gms or [])-set(eligible))
  if skipped:print('跳过未就绪窗口：'+', '.join(skipped)+'；详情见频道配置',flush=True)
  if not eligible:raise ValueError('所选窗口尚未完成权限、界面语言或运行绑定配置')
  gms=eligible
  if task_ids is None:l.plan(__import__('datetime').datetime.now(__import__('publisher').TZ).date().isoformat(),gms=gms)
 t=l.claim(gms=gms,manual=manual,mode=mode,schedule_window=schedule,concurrency=__import__('parallel_settings').read() if c.get('execution_engine')=='local' else 1,task_ids=task_ids)
 if not t:raise ValueError('没有可启动任务：请检查频道是否启用、今日是否已有草稿或发布记录、素材是否充足')
 ch=dict(l.db.execute('SELECT * FROM channels WHERE id=?',(t['channel_id'],)).fetchone());t.update(gm=ch['gm'],window_id=ch['window_id'])
 if schedule:t['schedule_window']={k:schedule[k] for k in ('start','end')}
 try:
  from parallel_settings import task_path,write
  t['publish_enabled']=mode=='public';write(task_path(t['id']),t)
  if c.get('execution_engine')!='local':write(ROOT/'.active-task.json',t)
  if c.get('execution_engine')=='local':
   import subprocess,sys
   folder=ROOT/'运行日志';folder.mkdir(exist_ok=True)
   with (folder/('task-'+t['id']+'.log')).open('ab') as log:
    child=subprocess.Popen([sys.executable,'-u',str(ROOT/'bit_runner.py'),'--task',t['id']],cwd=ROOT,stdout=log,stderr=log,start_new_session=True)
   print('已启动本机比特执行器，任务 '+t['id']+'，PID '+str(child.pid),flush=True)
   return
  task_id=c['native_tasks'][ch['gm']]
  req=urllib.request.Request('http://127.0.0.1:54345/rpa/run',json.dumps({'id':task_id}).encode(),{'Content-Type':'application/json'})
  with transport_urlopen(req,timeout=30) as r:result=json.load(r)
  if not result.get('success'):raise ValueError('比特任务启动失败')
 except Exception as e:
  l.report(t['id'],t['token'],'结果待核查',t['channel_id'],error=str(e));raise
if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('command',choices=['serve','dispatch']);a.add_argument('--gm',action='append');a.add_argument('--manual',action='store_true');a.add_argument('--task',action='append');a.add_argument('--mode',choices=['draft','public'],default='draft');x=a.parse_args()
 if x.command=='serve':HTTPServer(('127.0.0.1',18740),Handler).serve_forever()
 else:
  try:dispatch(x.gm,manual=x.manual,mode=x.mode,task_ids=x.task)
  except ValueError as e:
   print(str(e),flush=True)
   raise SystemExit(2)
