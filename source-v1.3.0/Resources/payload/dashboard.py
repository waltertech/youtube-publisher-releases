from local_transport import urlopen as transport_urlopen
"""Loopback-only dashboard; opening it never claims a task or uploads a file."""
import argparse, json, os, secrets, socket, subprocess, sys, threading, time
import urllib.request, urllib.error
import bit_windows
import feishu_auth
import local_settings
import material_rules
import scheduler
import acceptance
import schedule_settings
import parallel_settings
import manual_queue
from datetime import datetime
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from publisher import ROOT, Ledger, TZ

PORT=int(os.environ.get('YPP_DASHBOARD_PORT','18741'))
ORIGIN=f'http://127.0.0.1:{PORT}'
NONCE=secrets.token_urlsafe(32)
MUTEX=threading.Lock()
JOB={'running':False,'action':'','lines':[],'finished':None,'ok':None}
ACTIONS={'initialize_selected':['installation.py'],'refresh_materials':['scan_materials.py','--refresh'],'initialize':['installation.py'],'repair_cores':['installation.py','repair'],'scan':['scan_materials.py'],'plan':['publisher.py','plan'],'sync':['feishu_sync.py'],'dispatch':['bridge.py','dispatch'],'onboard':['onboard_windows.py'],'permissions':['probe_all_channels.py']}
LABELS={'initialize_selected':'自动配置选择频道','refresh_materials':'刷新未分配素材文案','initialize':'新电脑频道配置','repair_cores':'检查与修复旧内核','scan':'扫描素材','plan':'生成今日计划','sync':'同步飞书','dispatch':'手动启动任务','bridge':'启动桥接服务','windows':'刷新比特窗口','auth':'授权飞书','auth_finish':'完成飞书授权','onboard':'发现全部窗口频道','permissions':'核验频道上传权限'}
LOGDIR=ROOT/'运行日志'
LOGDIR.mkdir(exist_ok=True)

def bridge_ready():
 try:
  req=urllib.request.Request('http://127.0.0.1:18740/health',headers={'X-Publisher-Key':(ROOT/'.bridge-secret').read_text()})
  with transport_urlopen(req,timeout=1) as r:return json.load(r).get('service')=='ypp-bridge'
 except Exception:return False

def ensure_bridge():
 if bridge_ready():return '桥接服务已运行，已复用'
 with socket.socket() as s:
  if s.connect_ex(('127.0.0.1',18740))==0:raise ValueError('18740端口已占用但服务无法验证，请先处理旧服务；不会重复启动')
 with (LOGDIR/'bridge.log').open('ab') as f:
  subprocess.Popen([sys.executable,'-u',str(ROOT/'bridge.py'),'serve'],cwd=ROOT,stdout=f,stderr=f,start_new_session=True)
 for _ in range(20):
  if bridge_ready():return '桥接服务启动成功'
  time.sleep(.2)
 raise ValueError('桥接服务未就绪，请查看运行日志/bridge.log')

def dispatch_blockers(l,config,now,gms=None):
 reasons=[]
 if not config.get('draft_test_passed'):reasons.append('修复版完整回归尚未验收')
 if not config.get('bindings_verified'):reasons.append('调度器窗口绑定尚未启用')
 if not 10<=now.hour<18:reasons.append('当前不在台北时间10:00–18:00启动时段')
 if l.db.execute("SELECT 1 FROM tasks WHERE state IN ('上传中','填写中','检查中','发布中')").fetchone():reasons.append('已有执行中的任务')
 scope='' if gms is None else ' AND c.gm IN ('+','.join('?' for _ in gms)+')'
 t=l.db.execute("SELECT t.id,c.gm FROM tasks t JOIN channels c ON c.id=t.channel WHERE day=? AND state='待执行' AND c.enabled=1 AND c.verified=1"+scope+" ORDER BY ordinal LIMIT 1",(now.date().isoformat(),*(gms or []))).fetchone()
 if not t:reasons.append('没有已启用、已核实频道的今日待执行任务')
 elif not config.get('native_tasks',{}).get(t['gm']):reasons.append(t['gm']+'未配置原生任务ID')
 return reasons

TELEMETRIES={}
TELEMETRY={'task':None,'percent':None,'message':'尚未读取页面进度','observed_at':None}

def monitor_loop():
 while True:
  try:
   acceptance.check()
   l=Ledger()
   try:running=l.db.execute("SELECT id,channel,state FROM tasks WHERE state IN ('上传中','填写中','检查中','发布中')").fetchall()
   finally:l.db.close()
   from task_progress import collect
   active={t['id'] for t in running}
   for key in list(TELEMETRIES):
    if key not in active:TELEMETRIES.pop(key,None)
   def publish_progress(result):
    TELEMETRIES[result['task']]=result
   collect(running,publish_progress)

  except Exception as e:
   TELEMETRY.update(percent=None,message=str(e)[:180],observed_at=None)
  time.sleep(5)

def feishu_link():
 p=ROOT/'飞书配置.json'
 if not p.exists():return ''
 c=json.loads(p.read_text());token=c.get('base_token') or c.get('base',{}).get('base_token')
 return 'https://my.feishu.cn/base/'+token if token else ''

def snapshot(gms=None):
 l=Ledger();now=datetime.now(TZ)
 try:
  config=json.loads((ROOT/'调度配置.json').read_text())
  tasks=[]
  for r in l.db.execute('SELECT t.id,t.channel,t.day,t.ordinal,t.mode,t.manual,t.state,t.url,t.error,t.published,c.gm,c.name,a.payload FROM tasks t JOIN channels c ON c.id=t.channel LEFT JOIN assets a ON a.sha=t.sha ORDER BY day DESC,ordinal'):
   d=dict(r);a=json.loads(d.pop('payload') or '{}');d.update(filename=Path(a.get('video','')).name or '等待素材',title=a.get('title',''),video=a.get('video',''),bytes=a.get('video_size',0));tasks.append(d)
  assets=[]
  for r in l.db.execute('SELECT a.sha,a.payload,a.complete,t.state,t.channel FROM assets a LEFT JOIN tasks t ON t.sha=a.sha'):
   a=json.loads(r['payload'])
   if a.get('available') is False:continue
   assets.append({'id':r['sha'][:12],'filename':Path(a['video']).name,'title':a.get('title',''),'complete':bool(r['complete']),'state':r['state'] or ('可分配' if r['complete'] else '不完整'),'bytes':a.get('video_size',0),'missing_reasons':a.get('missing_reasons',[]),'folder':a.get('folder',''),'description_source':a.get('description_source',''),'description':a.get('description',''),'raw_description':a.get('raw_description',''),'hashtags':a.get('hashtags','')})
  logs=[dict(r) for r in l.db.execute('SELECT stage,start,error,recovery FROM logs ORDER BY start DESC LIMIT 30')]
  channels=[dict(r) for r in l.db.execute('SELECT gm,name,id,window_id,enabled,verified,reason FROM channels ORDER BY gm,id')]
  window_state=bit_windows.state()
  onboarding_path=ROOT/'窗口接入状态.json'
  onboarding=json.loads(onboarding_path.read_text()) if onboarding_path.exists() else {}
  window_items=[]
  for w in window_state['items']:
   cs=[c for c in channels if c['window_id']==w['id']]
   state=dict(onboarding.get(w['id'],{}));usable=sum(bool(c['enabled'] and c['verified']) for c in cs)
   if usable:state['status']='已接入本机执行器 · '+str(usable)+' 个频道可手动草稿'+('；另有 '+str(len(cs)-usable)+' 个频道待处理' if len(cs)>usable else '')
   elif cs and not state.get('error'):state['status']='；'.join(dict.fromkeys(c['reason'] for c in cs if c['reason']))
   window_items.append({**w,'channels':cs,'onboarding':state})
  scoped=None if gms is None else sorted({c['gm'] for c in channels if c['window_id'] in gms})
  blocked=[]
  for port in (18742,18744):
   with socket.socket() as probe:
    try:probe.bind(('127.0.0.1',port))
    except OSError:blocked.append('正在核查窗口或频道权限，完成后才可启动上传')
  if l.db.execute("SELECT count(*) FROM tasks WHERE state IN ('上传中','填写中','检查中','发布中')").fetchone()[0]>=parallel_settings.read():blocked.append('并行名额已满；等待正在执行的任务完成')
  for gm in scoped or []:
   cs=[c for c in channels if c['gm']==gm]
   if l.db.execute("SELECT 1 FROM tasks t JOIN channels c ON c.id=t.channel WHERE c.gm=? AND t.state='结果待核查'",(gm,)).fetchone():blocked.append(gm+'有结果待核查任务，仅暂停该窗口；其他窗口可继续')
   if not any(c['enabled'] and c['verified'] for c in cs):blocked.append(gm+'频道尚未核实启用')
   if not config.get('manual_ready',{}).get(gm) or (config.get('execution_engine')!='local' and not config.get('native_tasks',{}).get(gm)):blocked.append(gm+'运行条件尚未全部满足，请查看频道配置中的原因')
  if gms and any(x not in {c['window_id'] for c in channels} for x in gms):blocked.append('部分窗口尚未登记频道，会跳过；详情见窗口接入状态')
  if scoped:
   prior=l.db.execute("SELECT c.gm,t.state FROM tasks t JOIN channels c ON c.id=t.channel WHERE t.day=? AND c.gm IN ("+','.join('?' for _ in scoped)+") AND t.state!='待执行'",(now.date().isoformat(),*scoped)).fetchall()
   for r in prior:blocked.append(r['gm']+'今日已有'+r['state']+'任务；每频道每天最多一条')
  pending=l.db.execute('SELECT count(*) FROM outbox WHERE done=0').fetchone()[0]
 finally:l.db.close()
 ready=bridge_ready()
 if not ready:blocked.insert(0,'桥接服务未运行')
 with MUTEX:job=json.loads(json.dumps(JOB))
 publishable={c['id'] for w in window_items for c in w['channels'] if c['enabled'] and c['verified'] and config.get('manual_ready',{}).get(c['gm']) and (w['id'] not in onboarding or c['id'] in {ch['id'] for ch in onboarding[w['id']].get('channels',[])})}
 return {'publishable_channels_count':len(publishable),'version':'1.3.2','material_rules':material_rules.read(),'manual_queue':manual_queue.read(),'concurrency':parallel_settings.read(),'telemetries':dict(TELEMETRIES),'acceptance':acceptance.state(),'schedule':scheduler.state(),'service':'ypp-dashboard','time':now.isoformat(),'bridge':ready,'tasks':tasks,'assets':assets,'channels':channels,'windows':window_items,'window_updated':window_state['updated'],'window_error':window_state['error'],'logs':logs,'telemetry':dict(TELEMETRY),'job':job,'blockers':blocked,'sync_pending':pending,'mode':'手动启动 · 可选草稿或正式发布','public_ready':config.get('execution_engine')!='local' or bool(config.get('local_public_enabled')),'source':local_settings.read().get('material_dir','尚未选择素材目录'),'feishu':feishu_auth.state(),'base':feishu_link()}

def task_preview(task_id):
 import base64, mimetypes
 l=Ledger()
 try:
  r=l.db.execute('SELECT t.id,t.state,t.mode,t.url,c.gm,c.name,a.payload FROM tasks t JOIN channels c ON c.id=t.channel LEFT JOIN assets a ON a.sha=t.sha WHERE t.id=?',(task_id,)).fetchone()
  if not r:return None
  d=dict(r);a=json.loads(d.pop('payload') or '{}')
  q=manual_queue.read()
  if d['state']=='待执行' and q.get('enabled') and task_id in q.get('tasks',[]):d['mode']=q.get('mode',d['mode'])
  for key in ('title','description','tags','hashtags','raw_description','description_source'):d[key]=a.get(key,'')
  d['filename']=Path(a.get('video','')).name
  d['thumbnail']=None
  image=Path(a.get('thumbnail',''))
  if image.is_file() and image.suffix.lower() in ('.png','.jpg','.jpeg','.webp') and image.stat().st_size<=10*1024*1024:
   d['thumbnail']='data:'+mimetypes.guess_type(image.name)[0]+';base64,'+base64.b64encode(image.read_bytes()).decode()
  return d
 finally:l.db.close()

def append_line(line):
 with MUTEX:JOB['lines']=(JOB['lines']+[line])[-50:]

def run_action(action,gms=None,mode="draft"):
 ok=False
 try:
  if action=='auth':feishu_auth.begin();append_line('请在下方打开授权链接或扫码')
  elif action=='auth_finish':feishu_auth.finish();append_line('授权已完成，可以同步自己的台账')
  elif action=='windows':append_line('已读取 '+str(bit_windows.refresh())+' 个比特窗口')
  elif action=='bridge':append_line(ensure_bridge())
  else:
   if action=='dispatch':
    if not bridge_ready():raise ValueError('请先启动桥接服务')
   cmd=[sys.executable,'-u',str(ROOT/ACTIONS[action][0]),*ACTIONS[action][1:]]
   if action=='initialize_selected':
    for wid in gms:cmd.extend(['--window-id',wid])
    append_line('只配置所选窗口 ID：'+', '.join(gms))
   if action in ('plan','dispatch'):
    for gm in gms:cmd.extend(['--gm',gm])
    append_line('所选窗口：'+', '.join(gms))
   if action=='dispatch':
    l=Ledger()
    try:l.plan(datetime.now(TZ).date().isoformat(),gms)
    finally:l.db.close()
    manual_queue.begin(gms,mode)
    for task in manual_queue.read().get('tasks',[]):cmd.extend(['--task',task])
    cmd.extend(['--manual','--mode',mode]);append_line('手动运行 · '+('正式发布：检查通过后公开' if mode=='public' else '草稿：不会公开'))
   child=subprocess.Popen(cmd,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
   with (LOGDIR/(action+'.log')).open('a') as log:
    for line in child.stdout:
     line=line.rstrip();append_line(line);log.write(line+'\n');log.flush()
   if child.wait()!=0:raise ValueError('操作失败，请查看上方日志')
   if action=='dispatch':append_line('已进入手动队列：任务完成或中断后继续其他所选窗口；不会重复上传中断素材')
   append_line(LABELS[action]+'完成')
   if action=='sync':append_line('飞书台账：'+feishu_link())
  ok=True
 except Exception as e:append_line(str(e))
 finally:
  with MUTEX:JOB.update(running=False,ok=ok,finished=datetime.now(TZ).isoformat())

def start_action(action,gms=None,mode="draft"):
 if (ROOT/'.update-lock').exists():raise ValueError('正在等待安装应用更新，已暂停新操作')
 if mode not in ('draft','public'):raise ValueError('发布类型无效')
 if action not in {*ACTIONS,'bridge','windows','auth','auth_finish'}:raise ValueError('不支持的操作')
 if action=='initialize_selected':
  from window_scope import select_windows
  select_windows(bit_windows.state()['items'],gms)
 if action in ('plan','dispatch'):
  if not isinstance(gms,list) or not gms or len(gms)>10000 or any(not isinstance(g,str) for g in gms):raise ValueError('请至少选择一个窗口')
  l=Ledger()
  try:channels=[dict(r) for r in l.db.execute('SELECT gm,window_id FROM channels')]
  finally:l.db.close()
  gms=bit_windows.resolve(gms,channels)
  if not gms:raise ValueError('所选窗口尚未登记频道，请先核实频道及上传权限')
 with MUTEX:
  if JOB['running']:raise ValueError('已有操作正在运行，请等它完成')
  JOB.update(running=True,action=LABELS[action],lines=[],finished=None,ok=None)
 threading.Thread(target=run_action,args=(action,gms,mode),daemon=True).start()

class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def reply(self,code,data,kind='application/json'):
  body=(json.dumps(data,ensure_ascii=False) if kind=='application/json' else data).encode()
  self.send_response(code);self.send_header('Content-Type',kind+'; charset=utf-8');self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.send_header('X-Frame-Options','DENY');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
 def local_request(self):return self.headers.get('Host')==f'127.0.0.1:{PORT}' and self.headers.get('Origin',ORIGIN)==ORIGIN and self.headers.get('Sec-Fetch-Site','same-origin') in ('same-origin','none')
 def serve_video(self):
  import re,mimetypes
  from urllib.parse import parse_qs,urlsplit
  task_id=parse_qs(urlsplit(self.path).query).get('task',[''])[0]
  l=Ledger()
  try:r=l.db.execute('SELECT a.payload FROM tasks t JOIN assets a ON a.sha=t.sha WHERE t.id=?',(task_id,)).fetchone()
  finally:l.db.close()
  if not r:return self.reply(404,{'error':'任务不存在'})
  path=Path(json.loads(r[0]).get('video',''))
  if not path.is_file():return self.reply(404,{'error':'本地视频文件不存在'})
  size=path.stat().st_size;start=0;end=size-1;part=self.headers.get('Range')
  if part:
   m=re.fullmatch(r'bytes=(\d*)-(\d*)',part)
   try:
    if not m or not any(m.groups()):raise ValueError()
    if m[1]:start=int(m[1]);end=min(int(m[2]),size-1) if m[2] else size-1
    else:start=max(0,size-int(m[2]))
    if start>end or start>=size:raise ValueError()
   except ValueError:
    self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.send_header('Content-Length','0');self.end_headers();return
  self.send_response(206 if part else 200)
  self.send_header('Content-Type',mimetypes.guess_type(path.name)[0] or 'video/mp4')
  self.send_header('Accept-Ranges','bytes');self.send_header('Content-Length',str(end-start+1));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
  if part:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
  self.end_headers()
  try:
   with path.open('rb') as f:
    f.seek(start);remaining=end-start+1
    while remaining>0:
     chunk=f.read(min(256*1024,remaining))
     if not chunk:break
     self.wfile.write(chunk);remaining-=len(chunk)
  except (BrokenPipeError,ConnectionResetError):pass
 def do_GET(self):
  if not self.local_request():return self.reply(403,{'error':'仅允许本机看板访问'})
  if self.path=='/':return self.reply(200,(ROOT/'dashboard/index.html').read_text().replace('__NONCE__',NONCE),'text/html')
  if self.path.split('?')[0]=='/api/status':
   from urllib.parse import parse_qs,urlsplit
   query=parse_qs(urlsplit(self.path).query,keep_blank_values=True)
   return self.reply(200,snapshot(query.get('gm')))
  if self.path.startswith('/api/video?'):return self.serve_video()
  if self.path.startswith('/api/preview?'):
   from urllib.parse import parse_qs,urlsplit
   d=task_preview(parse_qs(urlsplit(self.path).query).get('task',[''])[0])
   return self.reply(200,d) if d else self.reply(404,{'error':'任务不存在'})
  if self.path=='/api/install-status':
   import installation
   return self.reply(200,installation.status())
  if self.path=='/workflow-template':
   body=(ROOT/'通用流程-无凭据.automa.json').read_bytes();self.send_response(200);self.send_header('Content-Type','application/octet-stream');self.send_header('Content-Disposition','attachment; filename=YouTube-workflow.automa.json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
  if self.path=='/health':return self.reply(200,{'service':'ypp-dashboard','version':'1.3.2','data_dir':str(ROOT)})
  self.reply(404,{'error':'未找到'})
 def do_POST(self):
  if (ROOT/'.update-lock').exists():return self.reply(409,{'error':'正在等待安装应用更新，已暂停新操作'})
  if not self.local_request() or self.headers.get('X-Dashboard-Token')!=NONCE:return self.reply(403,{'error':'请从本机看板操作'})
  try:
   n=int(self.headers.get('Content-Length',0))
   if n<0 or n>1048576:raise ValueError('请求过大')
   p=json.loads(self.rfile.read(n))
   if self.path=='/api/feishu-config':
    import installation
    return self.reply(200,installation.configure_feishu(p.get('app_id'),p.get('secret')))
   if self.path=='/api/manual-queue/stop':return self.reply(200,manual_queue.stop())
   if self.path=='/api/refresh-task':
    from refresh_task import refresh
    return self.reply(200,refresh(p.get('task','')))
   if self.path=='/api/stop-task':
    from task_control import stop
    return self.reply(200,stop(p.get('task','')))
   if self.path=='/api/start-task':return self.reply(202,manual_queue.enqueue(p.get('task','')))
   if self.path=='/api/review-task':
    from review_task import start
    return self.reply(202,start(p.get('task',''),confirmed=p.get('confirmed') is True))
   if self.path=='/api/retry-task':
    from retry_task import start
    return self.reply(202,start(p.get('task',''),confirmed_missing=p.get('confirmed_missing') is True))
   if self.path=='/api/publish-draft':
    from publish_draft import start
    start(p.get('task',''));return self.reply(202,{'ok':True})
   if self.path=='/api/material-rules':
    with MUTEX:
     if JOB['running']:raise ValueError('请等待当前看板操作完成后再保存素材识别规则')
     value=material_rules.save(p)
    return self.reply(200,{'rules':value})
   if self.path=='/api/material-folder/pick':return self.reply(200,{'path':local_settings.choose_folder()})
   if self.path=='/api/material-folder':
    with MUTEX:
     if JOB['running']:raise ValueError('请等待当前看板操作完成后再更换素材目录')
     path=local_settings.save_source(p.get('path'))
    if p.get('scan'):start_action('scan')
    return self.reply(200,{'path':path})
   if self.path=='/api/concurrency':return self.reply(200,{'concurrency':parallel_settings.save(p.get('concurrency'))})
   if self.path=='/api/schedule':
    value=schedule_settings.validate(p)
    known={w['id'] for w in bit_windows.state()['items']}
    if value['enabled'] and any(w not in known for w in value['window_ids']):raise ValueError('定时窗口已失效，请刷新窗口列表重新选择')
    saved=schedule_settings.save(value)
    scheduler.STATE.update(message='设置已保存，等待检查运行条件' if saved['enabled'] else '定时调度已关闭',checked_at=None)
    return self.reply(200,{'ok':True,'schedule':saved})
   if self.path!='/api/action':raise ValueError('无效接口')
   start_action(p['action'],p.get('gms'),p.get('mode','draft'));self.reply(202,{'ok':True})
  except Exception as e:self.reply(409,{'error':str(e)})

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--serve',action='store_true');args=parser.parse_args()
 if args.serve:
  threading.Thread(target=feishu_auth.loop,daemon=True).start()
  threading.Thread(target=bit_windows.loop,daemon=True).start()
  threading.Thread(target=monitor_loop,daemon=True).start()
  threading.Thread(target=scheduler.loop,args=(MUTEX,JOB),daemon=True).start()
  ThreadingHTTPServer(('127.0.0.1',PORT),Handler).serve_forever()
 else:
  def alive():
   try:
    with transport_urlopen(ORIGIN+'/health',timeout=1) as r:return json.load(r).get('service')=='ypp-dashboard'
   except Exception:return False
  if not alive():
   with (LOGDIR/'dashboard.log').open('ab') as f:subprocess.Popen([sys.executable,'-u',str(Path(__file__).resolve()),'--serve'],cwd=ROOT,stdout=f,stderr=f,start_new_session=True)
   for _ in range(30):
    if alive():break
    time.sleep(.2)
  if not alive():raise SystemExit('看板启动失败，请查看运行日志/dashboard.log')
  try:print(ensure_bridge())
  except Exception as e:print(e)
  import webbrowser
  webbrowser.open(ORIGIN)
