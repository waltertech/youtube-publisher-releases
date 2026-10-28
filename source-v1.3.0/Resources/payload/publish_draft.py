"""Publish an existing draft by video ID. Never uploads files."""
import json,re,uuid,argparse,subprocess,sys
from publisher import ROOT,Ledger,datetime,TZ
from bit_runner import open_page,switch_channel
from channel_probe import wait
from file_adapter import validate_draft_evidence
import parallel_settings

def reserve(task_id,ledger=None):
 l=ledger or Ledger()
 try:
  with l.tx():
   t=l.db.execute('SELECT t.*,c.window_id,c.gm,c.enabled,c.verified FROM tasks t JOIN channels c ON c.id=t.channel WHERE t.id=?',(task_id,)).fetchone()
   if not t or t['state']!='草稿':raise ValueError('仅草稿任务可以直接发布，请刷新任务列表')
   if not t['enabled'] or not t['verified']:raise ValueError('频道未启用或身份尚未核实')
   if not re.fullmatch(r'https://youtu\.be/[A-Za-z0-9_-]{11}',t['url'] or ''):raise ValueError('草稿缺少准确的视频链接，请先核查')
   active=l.db.execute("SELECT c.window_id,c.gm,t.state FROM tasks t JOIN channels c ON c.id=t.channel WHERE t.state IN ('上传中','填写中','检查中','发布中','结果待核查')").fetchall()
   if sum(x['state']!='结果待核查' for x in active)>=parallel_settings.read():raise ValueError('并行名额已满，请等待')
   if any(x['window_id']==t['window_id'] or x['gm']==t['gm'] for x in active):raise ValueError('此窗口已有运行中或待核查任务')
   today=datetime.now(TZ).date().isoformat()
   if l.db.execute("SELECT 1 FROM tasks WHERE channel=? AND id!=? AND state='已发布' AND substr(published,1,10)=?",(t['channel'],task_id,today)).fetchone():raise ValueError('此频道今天已正式发布一条视频')
   # Preserve the human decision for this exact existing video across publish attempts.
   reviewed=l.db.execute("SELECT 1 FROM sqlite_master WHERE name='human_reviews'").fetchone() and l.db.execute('SELECT created FROM human_reviews WHERE task=? AND video_url=? ORDER BY created DESC LIMIT 1',(task_id,t['url'])).fetchone()
   token=uuid.uuid4().hex
   if reviewed:l.db.execute('INSERT INTO human_reviews VALUES(?,?,?,?)',(task_id,token,t['url'],reviewed['created']))
   l.db.execute("UPDATE tasks SET state='检查中',mode='public',manual=1,token=?,run_window=?,error='' WHERE id=?",(token,t['window_id'] or t['gm'],task_id));l.queue('tasks',task_id)
   return {**dict(t),'token':token}
 finally:
  if ledger is None:l.db.close()

def restore(task_id,error):
 l=Ledger()
 try:
  with l.tx():
   l.db.execute("UPDATE tasks SET state='草稿',mode='draft',error=? WHERE id=? AND state='检查中'",(error,task_id));l.queue('tasks',task_id)
 finally:l.db.close()

def start(task_id):
 if (ROOT/'.update-lock').exists():raise ValueError('正在安装应用更新，已暂停新任务')
 import socket
 from contextlib import ExitStack
 with ExitStack() as stack:
  for port in (18742,18744):
   s=stack.enter_context(socket.socket())
   try:s.bind(('127.0.0.1',port))
   except OSError:raise ValueError('正在核查频道，请稍后发布草稿')
  reserve(task_id)
  try:
   with (ROOT/'运行日志'/('task-'+task_id+'.log')).open('ab') as log:subprocess.Popen([sys.executable,'-u',str(ROOT/'publish_draft.py'),'--task',task_id],cwd=ROOT,stdout=log,stderr=log,start_new_session=True)
  except Exception as e:restore(task_id,str(e));raise

def execute(task_id):
 l=Ledger();t=dict(l.db.execute('SELECT t.*,c.window_id FROM tasks t JOIN channels c ON c.id=t.channel WHERE t.id=?',(task_id,)).fetchone());b=c=None;publishing=False
 try:
  if t['state']!='检查中' or t['mode']!='public':raise ValueError('草稿发布任务已失效')
  from task_control import register
  register(task_id,t['token'],window_id=t['window_id'])
  b,tid,c=open_page(t['window_id']);register(task_id,t['token'],tid,t['window_id']);switch_channel(c,t['channel']);vid=t['url'].rsplit('/',1)[-1]
  c.call('Page.navigate',{'url':'https://studio.youtube.com/video/'+vid+'/edit'})
  wait(c,"[...document.querySelectorAll('button')].some(x=>['Edit draft','编辑草稿','編輯草稿'].includes(x.innerText.trim()))")
  c.evaluate("[...document.querySelectorAll('button')].find(x=>['Edit draft','编辑草稿','編輯草稿'].includes(x.innerText.trim())).click()")
  wait(c,"document.querySelector('ytcp-uploads-dialog')?.innerText.includes("+json.dumps(t['url'])+")")
  evidence=c.evaluate("({text:document.querySelector('ytcp-uploads-dialog').innerText,links:[...document.querySelectorAll('ytcp-uploads-dialog a[href]')].map(x=>x.href)})")
  from review_task import approved
  if validate_draft_evidence(evidence,reviewed=approved({'id':task_id,'token':t['token']},t['url']))!=t['url']:raise ValueError('草稿视频 ID 不一致')
  for _ in range(4):
   if c.evaluate("!!document.querySelector('tp-yt-paper-radio-button[name=PUBLIC]')"):break
   c.evaluate("(()=>{const b=[...document.querySelectorAll('ytcp-uploads-dialog button')].find(x=>['Next','下一步'].includes(x.innerText.trim())&&!x.disabled);if(!b)throw Error('找不到下一步');b.click()})()")
   import time;time.sleep(1)
  wait(c,"!!document.querySelector('tp-yt-paper-radio-button[name=PUBLIC]')")
  c.evaluate("document.querySelector('tp-yt-paper-radio-button[name=PUBLIC]').click()")
  if not c.evaluate("document.querySelector('tp-yt-paper-radio-button[name=PUBLIC]').checked"):raise ValueError('无法确认公开选项')
  l.report(task_id,t['token'],'发布中',t['channel'],url=t['url']);publishing=True
  c.evaluate("(()=>{const b=[...document.querySelectorAll('ytcp-uploads-dialog button')].find(x=>['Publish','发布','發佈'].includes(x.innerText.trim())&&!x.disabled);if(!b)throw Error('发布按钮不可用');b.click()})()")
  wait(c,"[...document.querySelectorAll('[role=dialog]')].some(x=>x.getBoundingClientRect().width>0&&/Video published|视频已发布|影片已發布/.test(x.innerText)&&x.innerText.includes("+json.dumps(t['url'])+"))",timeout=120)
  l.report(task_id,t['token'],'已发布',t['channel'],url=t['url'],video_id=vid,public=True);print('已有草稿正式发布成功：'+t['url'],flush=True)
 except Exception as e:
  if publishing:l.report(task_id,t['token'],'结果待核查',t['channel'],error=str(e))
  else:restore(task_id,str(e))
  raise
 finally:
  if c:c.close()
  if b:b.close()
  l.db.close()
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--task',required=True);a=p.parse_args();execute(a.task)
