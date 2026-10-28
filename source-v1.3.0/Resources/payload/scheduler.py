"""Dashboard-owned scheduler; SQLite remains the sole upload task owner."""
import json,subprocess,sys,time,threading
from datetime import datetime
from publisher import ROOT,Ledger,TZ
import schedule_settings as settings
STATE={'message':'定时调度已关闭','checked_at':None}
def tick(now=None,launch=None):
 if (ROOT/'.update-lock').exists():STATE['message']='等待安装应用更新，已暂停新任务';return
 now=now or datetime.now(TZ);s=settings.read();STATE['checked_at']=now.isoformat()
 if not s['enabled']:STATE['message']='定时调度已关闭';return
 cfg=json.loads((ROOT/'调度配置.json').read_text());blocked=settings.blockers(cfg,s)
 if blocked:STATE['message']='已保存启用意愿，等待：'+'；'.join(blocked);return
 if not settings.in_window(now,s):STATE['message']='等待每日 '+s['start']+'–'+s['end']+'（台北）';return
 l=Ledger()
 try:
  import parallel_settings
  if l.db.execute("SELECT count(*) FROM tasks WHERE state IN ('上传中','填写中','检查中','发布中')").fetchone()[0]>=parallel_settings.read():STATE['message']='并行名额已满，等待正在执行的任务完成';return
  channels=[dict(r) for r in l.db.execute('SELECT * FROM channels')]
  gms=sorted({c['gm'] for c in channels if c['window_id'] in s['window_ids'] and c['enabled'] and c['verified'] and cfg.get('manual_ready',{}).get(c['gm'])})
  if not gms:STATE['message']='所选窗口没有已就绪频道';return
  l.plan(now.astimezone(TZ).date().isoformat(),gms)
  pending=l.db.execute("SELECT 1 FROM tasks t JOIN channels c ON c.id=t.channel WHERE day=? AND state='待执行' AND c.enabled=1 AND c.verified=1 AND c.gm IN ("+','.join('?' for _ in gms)+")",(now.astimezone(TZ).date().isoformat(),*gms)).fetchone()
  if not pending:STATE['message']='今日无待执行任务；缺素材时请先扫描素材';return
 finally:l.db.close()
 if launch:launch(gms,s['mode'])
 else:
  cmd=[sys.executable,'-u',str(ROOT/'bridge.py'),'dispatch','--mode',s['mode']]
  for gm in gms:cmd+=['--gm',gm]
  with (ROOT/'运行日志/scheduler.log').open('ab') as log:
   result=subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=log,timeout=60)
  if result.returncode:raise ValueError('启动被拦截；详见运行日志/scheduler.log')
 STATE['message']='已填充空闲并行名额，完成后继续补位'
def loop(mutex,job):
 while True:
  try:
   with mutex:busy=job['running']
   if not busy:
    import manual_queue
    manual_queue.tick()
    if not manual_queue.read().get('enabled'):tick()
  except Exception as e:STATE['message']='调度暂停重试：'+str(e)
  time.sleep(5)
def state():return {**settings.read(),**STATE}
