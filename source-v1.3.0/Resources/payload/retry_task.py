"""Explicit human-confirmed restart; preserves global material ownership and archives prior attempts."""
import argparse,json,subprocess,sys,uuid
from pathlib import Path
from publisher import ROOT,Ledger,datetime,TZ
import parallel_settings

PHASES={'填写中':7,'检查中':15,'发布中':16}
def resume_point(task,ledger,checkpoint):
 if checkpoint:
  index=checkpoint.get('node')
  if type(index) is not int or not 7<=index<=19:raise ValueError('中断位置不明确，请人工核查原视频')
  phase=checkpoint.get('phase')
  if phase not in PHASES:raise ValueError('缺少可靠的中断阶段，请人工核查原视频')
  if phase=='发布中' and checkpoint.get('variables',{}).get('public_selected') is True:index=19
  return index,phase
 prior=ledger.db.execute("SELECT stage FROM logs WHERE task=? AND stage IN ('填写中','检查中','发布中') ORDER BY start DESC,rowid DESC LIMIT 1",(task['id'],)).fetchone()
 if not prior:raise ValueError('缺少中断记录，请人工核查原视频')
 phase=prior['stage']
 if phase=='发布中':raise ValueError('旧任务的公开提交结果不明，不能重复点击发布；请先人工确认原视频')
 return PHASES[phase],phase

def reserve(task_id,ledger=None,payload=None,checkpoint=None,in_transaction=False):
 l=ledger or Ledger()
 try:
  from contextlib import nullcontext
  with nullcontext() if in_transaction else l.tx():
   t=l.db.execute('SELECT t.*,c.window_id,c.enabled,c.verified FROM tasks t JOIN channels c ON c.id=t.channel WHERE t.id=?',(task_id,)).fetchone()
   if not t or t['state']!='结果待核查':raise ValueError('仅结果待核查任务可重试，请刷新列表')
   if not t['enabled'] or not t['verified']:raise ValueError('频道未启用或身份未核实，请先处理频道配置')
   if not payload or payload.get('id')!=task_id or payload.get('token')!=t['token'] or payload.get('channel_id')!=t['channel'] or payload.get('window_id')!=t['window_id']:raise ValueError('缺少匹配的原任务输入，禁止新建上传')
   if not payload.get('target_id'):raise ValueError('原任务页面标识缺失，请人工核查原视频')
   if not l.db.execute("SELECT 1 FROM sqlite_master WHERE name='file_submissions'").fetchone():raise ValueError('无原文件提交记录，无法确认重试安全')
   submission=l.db.execute("SELECT state FROM file_submissions WHERE task=? AND kind='video'",(task_id,)).fetchone()
   if not submission or submission['state']!='已提交':raise ValueError('原视频是否提交不明确，请先人工核查；不会直接重传')
   if l.db.execute("SELECT 1 FROM tasks other JOIN channels c ON c.id=other.channel WHERE other.id!=? AND other.state IN ('上传中','填写中','检查中','发布中','结果待核查') AND c.window_id=?",(task_id,t['window_id'])).fetchone():raise ValueError('原窗口有其他任务，请先处理')
   count=l.db.execute("SELECT count(*) FROM tasks WHERE id!=? AND state IN ('上传中','填写中','检查中','发布中')",(task_id,)).fetchone()[0]
   if count>=parallel_settings.read():raise ValueError('并行名额已满，请稍后重试')
   index,phase=resume_point(t,l,checkpoint)
   token=uuid.uuid4().hex
   l.db.execute('UPDATE tasks SET state=?,token=?,error=? WHERE id=?',(phase,token,'正在核查原上传页并恢复；不会重新上传视频',task_id));l.queue('tasks',task_id)
   now=datetime.now(TZ).isoformat();key=uuid.uuid4().hex
   l.db.execute('INSERT INTO logs VALUES(?,?,?,?,?,?,?,?)',(key,task_id,'重试',now,now,'','','保留原素材占用；核对原页面后续执行'));l.queue('logs',key)
   return {**payload,'token':token},index
 finally:
  if ledger is None:l.db.close()

def reserve_restart(task_id,confirmed_missing=False,ledger=None,payload=None,checkpoint=None):
 if confirmed_missing is not True:raise ValueError('重试表示你已人工确认原视频未上传成功；请刷新工作台后点击重试')
 l=ledger or Ledger()
 try:
  with l.tx():
   t=l.db.execute('SELECT t.*,c.window_id,c.enabled,c.verified,c.gm FROM tasks t JOIN channels c ON c.id=t.channel WHERE t.id=?',(task_id,)).fetchone()
   if not t or t['state']!='结果待核查':raise ValueError('仅结果待核查任务可重试，请刷新列表')
   if t['published']:raise ValueError('已有发布完成记录，不允许重新上传')
   if not t['enabled'] or not t['verified']:raise ValueError('频道未启用或身份未核实')
   if not payload or payload.get('id')!=task_id or payload.get('token')!=t['token'] or payload.get('channel_id')!=t['channel'] or payload.get('window_id')!=t['window_id']:raise ValueError('原任务输入与频道不匹配')
   other=l.db.execute("SELECT t.id,t.state,c.window_id,c.gm FROM tasks t JOIN channels c ON c.id=t.channel WHERE t.id!=? AND t.state IN ('上传中','填写中','检查中','发布中','结果待核查')",(task_id,)).fetchall()
   if sum(r['state']!='结果待核查' for r in other)>=parallel_settings.read():raise ValueError('并行名额已满，请稍后重试')
   if any(r['window_id']==t['window_id'] or r['gm']==t['gm'] for r in other):raise ValueError('原窗口有其他执行中或待核查任务，请先处理')
   today=datetime.now(TZ).date().isoformat()
   if l.db.execute("SELECT 1 FROM tasks WHERE channel=? AND id!=? AND state='已发布' AND substr(published,1,10)=?",(t['channel'],task_id,today)).fetchone():raise ValueError('该频道今天已有公开发布，不能超过每日限额')
   submissions=[]
   if l.db.execute("SELECT 1 FROM sqlite_master WHERE name='file_submissions'").fetchone():
    submissions=[dict(r) for r in l.db.execute('SELECT * FROM file_submissions WHERE task=?',(task_id,))]
   l.db.execute('CREATE TABLE IF NOT EXISTS retry_attempts(id TEXT PRIMARY KEY,task TEXT,created TEXT,evidence TEXT)')
   now=datetime.now(TZ).isoformat();attempt=uuid.uuid4().hex
   evidence={'task':dict(t),'input':payload,'checkpoint':checkpoint,'file_submissions':submissions,'confirmed_missing':True}
   l.db.execute('INSERT INTO retry_attempts VALUES(?,?,?,?)',(attempt,task_id,now,json.dumps(evidence,ensure_ascii=False)))
   if submissions:l.db.execute('DELETE FROM file_submissions WHERE task=?',(task_id,))
   token=uuid.uuid4().hex
   l.db.execute("UPDATE tasks SET state='上传中',token=?,manual=1,url=NULL,error='' WHERE id=?",(token,task_id));l.queue('tasks',task_id)
   key=uuid.uuid4().hex;l.db.execute('INSERT INTO logs VALUES(?,?,?,?,?,?,?,?)',(key,task_id,'人工确认后重新上传',now,now,'','','用户点击重试，确认原视频未上传成功；归档原尝试并从上传入口完整执行，任务和素材分配保持不变'));l.queue('logs',key)
   result={**payload,'token':token,'manual':True,'mode':t['mode'],'publish_enabled':t['mode']=='public','visibility':'public' if t['mode']=='public' else 'private','retry_attempt':attempt}
   result.pop('target_id',None)
   return result
 finally:
  if ledger is None:l.db.close()

def start(task_id,confirmed_missing=False):
 if confirmed_missing is not True:raise ValueError('请刷新工作台并点击重试；点击表示已人工确认原视频未上传成功')
 if (ROOT/'.update-lock').exists():raise ValueError('正在等待应用更新，暂不能重试')
 from contextlib import ExitStack
 import socket
 path=parallel_settings.task_path(task_id);checkpoint_path=parallel_settings.task_path(task_id,'checkpoint')
 if not path.exists():raise ValueError('原任务输入不存在')
 with ExitStack() as stack:
  for port in (18742,18744):
   s=stack.enter_context(socket.socket())
   try:s.bind(('127.0.0.1',port))
   except OSError:raise ValueError('正在配置频道或启动任务，请稍后重试')
  original=json.loads(path.read_text())
  for kind in ('video','thumbnail'):
   if not Path(original.get(kind,'/missing')).is_file():raise ValueError('原素材文件不存在：'+kind+'，请恢复素材文件')
  config=json.loads((ROOT/'调度配置.json').read_text())
  if config.get('execution_engine')!='local':raise ValueError('完整重试需要使用本机执行器')
  if original.get('mode')=='public' and not config.get('local_public_enabled'):raise ValueError('正式发布未启用')
  a=reserve_restart(task_id,confirmed_missing=True,payload=original,checkpoint=json.loads(checkpoint_path.read_text()) if checkpoint_path.exists() else None)
  try:
   parallel_settings.write(path,a)
   for kind in ('checkpoint','monitor'):
    stale=parallel_settings.task_path(task_id,kind)
    if stale.exists():stale.unlink()
   with (ROOT/'运行日志'/('task-'+task_id+'.log')).open('ab') as log:
    subprocess.Popen([sys.executable,'-u',str(ROOT/'bit_runner.py'),'--task',task_id],cwd=ROOT,stdout=log,stderr=log,start_new_session=True)
  except Exception as e:
   l=Ledger()
   try:l.report(task_id,a['token'],'结果待核查',a['channel_id'],error='无法启动完整重试：'+str(e))
   finally:l.db.close()
   raise
 return {'ok':True,'message':'已按人工确认重新打开窗口，从选择视频开始完整执行上传和发布'}

if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--task',required=True);parser.add_argument('--confirmed-missing',action='store_true');args=parser.parse_args();start(args.task,confirmed_missing=args.confirmed_missing)
