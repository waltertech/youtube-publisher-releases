"""Stop one task's local worker and its exact automation tab, retaining material ownership."""
import json,os,signal,subprocess,uuid,re
from publisher import ROOT,Ledger,datetime,TZ
from parallel_settings import task_path,write
ACTIVE=('上传中','填写中','检查中','发布中')
def register(task,token,target_id='',window_id=''):
 write(task_path(task,'worker'),{'task':task,'token':token,'pid':os.getpid(),'target_id':target_id,'window_id':window_id})
def stop(task):
 l=Ledger()
 try:
  t=l.db.execute('SELECT * FROM tasks WHERE id=?',(task,)).fetchone()
  if not t or t['state'] not in ACTIVE:raise ValueError('任务已结束或已停止，请刷新')
  path=task_path(task,'worker');worker=json.loads(path.read_text()) if path.exists() else {}
  # Existing workers predate registration; match the exact task argument and source directory.
  rows=subprocess.check_output(['ps','-axo','pid=,command='],text=True).splitlines()
  targets=[]
  for row in rows:
   parts=row.strip().split(None,1)
   if len(parts)!=2:continue
   command=parts[1]
   if any(re.search(re.escape(str(ROOT/name))+r'\s+--task\s+'+re.escape(task)+r'(?:\s|$)',command) for name in ('bit_runner.py','publish_draft.py')):targets.append(int(parts[0]))
  for pid in targets:
   try:os.kill(pid,signal.SIGTERM)
   except ProcessLookupError:pass
  # Closing the task-owned tab also stops page-side asynchronous automation/upload.
  if worker.get('token')!=t['token']:
   p=task_path(task)
   a=json.loads(p.read_text()) if p.exists() else {}
   worker=a if a.get('token')==t['token'] else {}
  close_error=''
  if worker.get('target_id') and worker.get('window_id'):
   try:
    from onboard_windows import api
    from file_adapter import CDP
    browser=CDP(api('browser/open',{'id':worker['window_id']})['ws'])
    try:browser.call('Target.closeTarget',{'targetId':worker['target_id']})
    finally:browser.close()
   except Exception as exc:close_error='；原任务页关闭失败，请在比特窗口手动停止：'+str(exc)
  else:close_error='；未记录原任务页，请在比特窗口确认上传已停止'
  with l.tx():
   current=l.db.execute('SELECT state,token FROM tasks WHERE id=?',(task,)).fetchone()
   if current['token']!=t['token'] or current['state'] not in ACTIVE:return {'ok':True,'message':'任务状态已改变，请刷新核查'}
   message='用户已停止任务，保留原视频与素材占用，后续请核查已有草稿'+close_error
   l.db.execute("UPDATE tasks SET state='结果待核查',error=? WHERE id=?",(message,task));l.queue('tasks',task)
   now=datetime.now(TZ).isoformat();key=uuid.uuid4().hex
   l.db.execute('INSERT INTO logs VALUES(?,?,?,?,?,?,?,?)',(key,task,'人工停止',now,now,'','',message));l.queue('logs',key)
  return {'ok':True,'message':message}
 finally:l.db.close()
