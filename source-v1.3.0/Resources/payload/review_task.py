"""Human approval of a copyright finding, bound to the original task/video/token."""
import json,uuid,subprocess,sys,socket
from contextlib import ExitStack
from publisher import ROOT,Ledger,datetime,TZ
import parallel_settings
from retry_task import reserve

def approve(task_id,payload,checkpoint,ledger=None):
 l=ledger or Ledger()
 try:
  t=l.db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
  if not t or t['state']!='结果待核查' or not any(word in (t['error'] or '') for word in ('版权','Copyright')):raise ValueError('此按钮仅用于人工核查版权检查问题；其他中断请使用重试')
  import re
  url=(checkpoint or {}).get('video_url','')
  if not re.fullmatch(r'https://youtu\.be/[A-Za-z0-9_-]{11}',url):raise ValueError('缺少原视频 ID，不能通过核查')
  if checkpoint.get('node') not in (15,19):raise ValueError('原任务检查尚未完成，请先在比特窗口检查原视频')
  with l.tx():
   a,index=reserve(task_id,l,payload,checkpoint,in_transaction=True)
   l.db.execute('CREATE TABLE IF NOT EXISTS human_reviews(task TEXT,token TEXT,video_url TEXT,created TEXT,PRIMARY KEY(task,token))')
   now=datetime.now(TZ).isoformat()
   l.db.execute('INSERT INTO human_reviews VALUES(?,?,?,?)',(task_id,a['token'],url,now))
   key=uuid.uuid4().hex;l.db.execute('INSERT INTO logs VALUES(?,?,?,?,?,?,?,?)',(key,task_id,'人工核查通过',now,now,'','','用户确认原视频版权检查可接受；仅继续该视频，不重新上传'));l.queue('logs',key)
   a['manual']=True
   l.db.execute('UPDATE tasks SET manual=1 WHERE id=?',(task_id,))
   return a,index
 finally:
  if ledger is None:l.db.close()

def approved(a,url):
 l=Ledger()
 try:
  if not l.db.execute("SELECT 1 FROM sqlite_master WHERE name='human_reviews'").fetchone():return False
  return bool(l.db.execute('SELECT 1 FROM human_reviews WHERE task=? AND token=? AND video_url=?',(a['id'],a['token'],url)).fetchone())
 finally:l.db.close()

def start(task_id,confirmed=False):
 if confirmed is not True:raise ValueError('请确认你已人工检查原视频并同意继续')
 if (ROOT/'.update-lock').exists():raise ValueError('正在更新，暂不能启动')
 with ExitStack() as stack:
  for port in (18742,18744):
   sock=stack.enter_context(socket.socket())
   try:sock.bind(('127.0.0.1',port))
   except OSError:raise ValueError('正在启动其他任务，请稍后重试')
  config=json.loads((ROOT/'调度配置.json').read_text())
  if config.get('execution_engine')!='local':raise ValueError('人工核查继续需要本机执行器')
  path=parallel_settings.task_path(task_id);checkpoint_path=parallel_settings.task_path(task_id,'checkpoint')
  payload=json.loads(path.read_text());checkpoint=json.loads(checkpoint_path.read_text())
  if payload.get('mode')=='public' and not config.get('local_public_enabled'):raise ValueError('正式发布未启用')
  a,index=approve(task_id,payload,checkpoint)
  try:
   parallel_settings.write(path,a)
   with (ROOT/'运行日志'/('task-'+task_id+'.log')).open('ab') as log:
    subprocess.Popen([sys.executable,'-u',str(ROOT/'bit_runner.py'),'--task',task_id,'--resume',str(index)],cwd=ROOT,stdout=log,stderr=log,start_new_session=True)
  except Exception as exc:
   l=Ledger()
   try:l.report(task_id,a['token'],'结果待核查',a['channel_id'],error=str(exc))
   finally:l.db.close()
   raise
 return {'ok':True,'message':'已记录人工核查通过，正在核对原频道和视频并继续，不重新上传'}
