"""Continue only the tasks captured by a user's manual start; quarantine failed windows."""
import json,threading,subprocess,sys
from publisher import ROOT,Ledger,datetime,TZ
from parallel_settings import read as concurrency,write
LOCK=threading.RLock()
PATH=ROOT/'手动队列.json'
def read():
 with LOCK:return json.loads(PATH.read_text()) if PATH.exists() else {'enabled':False,'message':'手动队列未启动'}
def begin(gms,mode,now=None):
 now=now or datetime.now(TZ);l=Ledger()
 try:
  rows=l.db.execute("SELECT t.id FROM tasks t JOIN channels c ON c.id=t.channel WHERE day<=? AND c.gm IN ("+','.join('?' for _ in gms)+") AND state IN ('待执行','上传中','填写中','检查中','发布中','结果待核查')",(now.date().isoformat(),*gms)).fetchall()
 finally:l.db.close()
 with LOCK:write(PATH,{'enabled':bool(rows),'day':now.date().isoformat(),'gms':gms,'mode':mode,'tasks':[r['id'] for r in rows],'message':'手动队列已启用，任务完成或中断后继续其他窗口'})
def stop():
 with LOCK:
  q=read();q.update(enabled=False,message='已停止继续启动；正在执行的任务不会中止');write(PATH,q)
 return q

def enqueue(task_id):
 with LOCK:
  l=Ledger()
  try:
   task=l.db.execute("SELECT t.id,t.state,t.mode,c.gm FROM tasks t JOIN channels c ON c.id=t.channel WHERE t.id=?",(task_id,)).fetchone()
   if not task or task['state']!='待执行':raise ValueError('任务已不是待执行，请刷新')
  finally:l.db.close()
  q=read();today=datetime.now(TZ).date().isoformat()
  if q.get('enabled') and q.get('mode')!=task['mode']:raise ValueError('请先停止当前不同发布类型的队列')
  if not q.get('enabled'):q={'tasks':[],'gms':[],'mode':task['mode']}
  q.update(enabled=True,day=today,message='已加入手动队列，空闲名额可用时启动；其他窗口中断不会阻塞')
  if task_id not in q['tasks']:q['tasks'].append(task_id)
  if task['gm'] not in q['gms']:q['gms'].append(task['gm'])
  write(PATH,q)
  return {'ok':True,'message':q['message']}

def tick(now=None,launch=None):
 with LOCK:
  q=read()
  if not q.get('enabled') or (ROOT/'.update-lock').exists():return
  now=now or datetime.now(TZ)
  if q['day']!=now.date().isoformat():q.update(enabled=False,message='日期已变化，手动队列已结束；不自动补发旧任务');write(PATH,q);return
  l=Ledger()
  try:
   ids=q['tasks'];marks=','.join('?' for _ in ids)
   rows=l.db.execute("SELECT t.id,t.state,c.gm,c.window_id FROM tasks t JOIN channels c ON c.id=t.channel WHERE t.id IN ("+marks+")",ids).fetchall()
   all_busy=l.db.execute("SELECT t.state,c.gm,c.window_id FROM tasks t JOIN channels c ON c.id=t.channel WHERE t.state IN ('上传中','填写中','检查中','发布中','结果待核查')").fetchall()
   running=sum(r['state']!='结果待核查' for r in all_busy)
   blocked_windows={(r['window_id'] or r['gm']) for r in all_busy}
   pending=[r['id'] for r in rows if r['state']=='待执行' and (r['window_id'] or r['gm']) not in blocked_windows]
   own_running=any(r['state'] in ('上传中','填写中','检查中','发布中') for r in rows)
  finally:l.db.close()
  if not pending and not own_running:
   q.update(enabled=False,message='手动队列已结束；待核查任务及其窗口保留暂停，其他窗口不受影响');write(PATH,q);return
  if running>=concurrency() or not pending:return
  if launch:launch(q['gms'],q['mode'],pending)
  else:
   command=[sys.executable,'-u',str(ROOT/'bridge.py'),'dispatch','--manual','--mode',q['mode']]
   for gm in q['gms']:command+=['--gm',gm]
   for task in pending:command+=['--task',task]
   with (ROOT/'运行日志/manual-queue.log').open('ab') as log:
    result=subprocess.run(command,cwd=ROOT,stdout=log,stderr=log,timeout=60)
   if result.returncode:q['message']='等待可用窗口或运行条件；详见运行日志/manual-queue.log';write(PATH,q);return
  q['message']='已继续空闲窗口；中断任务单独保留待核查';write(PATH,q)
