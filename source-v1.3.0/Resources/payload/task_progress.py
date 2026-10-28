"""Read-only, independently bounded progress observations for each task."""
import json,re
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime
from publisher import TZ
from parallel_settings import task_path
from file_adapter import CDP

EXPRESSION=r"""(()=>{const ds=[...document.querySelectorAll('ytcp-uploads-dialog')].filter(e=>e.getClientRects().length);const d=ds.length===1?ds[0]:null;return {channel:[...document.querySelectorAll('a[href]')].map(a=>a.href).find(x=>/^https:\/\/studio.youtube.com\/channel\/UC/.test(x)),dialogs:ds.length,text:d?.innerText||'',status:d?[...d.querySelectorAll('ytcp-video-upload-progress,ytcp-video-upload-progress-bar,#upload-progress')].filter(e=>e.getClientRects().length).map(e=>e.innerText).join('\n'):''}})()"""

def parse_progress(observed):
 text=observed.get('status') or observed.get('text','')
 matches=list(re.finditer(r'(?:Uploading\s*|正在上传[^\n%]*?|上传中[^\n%]*?)(\d{1,3})\s*%[^\n]*',text,re.I))
 values={int(m.group(1)) for m in matches}
 if len(values)==1 and 0<=next(iter(values))<=100:return next(iter(values)),matches[0].group(0)
 if len(values)>1:raise ValueError('页面包含多个上传进度，等待明确的任务进度')
 message=next((s.strip() for s in text.splitlines() if re.search(r'Checks complete|Processing|检查完成|处理中|上传完成|Upload complete',s,re.I)),'等待页面提供上传进度')
 return None,message

def observe(task):
 result={'task':task['id'],'percent':None,'observed_at':None}
 try:
  p=task_path(task['id'],'monitor')
  if not p.exists():raise ValueError('等待此任务建立进度连接')
  endpoint=json.loads(p.read_text())
  if endpoint.get('task')!=task['id'] or endpoint.get('channel')!=task['channel']:raise ValueError('进度连接与任务不匹配')
  c=CDP(endpoint['ws'],timeout=5)
  try:observed=c.evaluate(EXPRESSION)
  finally:c.close()
  if (observed.get('channel') or '').split('/channel/')[-1].split('/')[0]!=task['channel']:raise ValueError('页面频道与任务不匹配')
  if observed.get('dialogs')!=1:raise ValueError('没有唯一的上传对话框，等待页面进度')
  percent,message=parse_progress(observed)
  result.update(percent=percent,message=message,observed_at=datetime.now(TZ).isoformat())
 except Exception as e:result['message']='进度暂不可用：'+str(e)[:180]
 return result

def collect(tasks,publish):
 if not tasks:return
 with ThreadPoolExecutor(max_workers=5) as pool:
  futures=[pool.submit(observe,dict(task)) for task in tasks]
  for future in as_completed(futures):publish(future.result())
