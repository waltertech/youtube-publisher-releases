"""Read all BitBrowser profiles, projecting only identity metadata."""
import json,urllib.request,threading,time
from datetime import datetime
from publisher import TZ
LOCK=threading.Lock()
CACHE={'items':[],'updated':None,'error':'正在读取比特窗口'}
def fetch_all():
 items={};page=0
 while True:
  req=urllib.request.Request('http://127.0.0.1:54345/browser/list',json.dumps({'page':page,'pageSize':100}).encode(),{'Content-Type':'application/json'})
  with urllib.request.urlopen(req,timeout=8) as r:result=json.load(r)
  if not result.get('success'):raise ValueError('比特窗口接口读取失败')
  d=result['data'];rows=d.get('list',[]);previous=len(items)
  for row in rows:
   items[row['id']]={'id':row['id'],'name':row.get('name') or '未命名窗口','seq':row.get('seq',0)}
  if len(items)>=d.get('totalNum',len(items)) or not rows:break
  if len(items)==previous:raise ValueError('窗口分页没有推进，列表尚未完整')
  page+=1
 return sorted(items.values(),key=lambda r:(r['name'],r['seq']))
def refresh():
 try:
  items=fetch_all()
  with LOCK:CACHE.update(items=items,updated=datetime.now(TZ).isoformat(),error='')
 except Exception:
  with LOCK:CACHE['error']='无法连接比特浏览器，保留上次列表；请打开比特后刷新'
  raise
 return len(items)
def state():
 with LOCK:return {**CACHE,'items':[dict(x) for x in CACHE['items']]}
def loop():
 while True:
  try:refresh()
  except Exception:pass
  time.sleep(60)
def resolve(ids,channels):
 """UI values are profile IDs, never names that can collide."""
 cache=state();known={x['id'] for x in cache['items']}
 if any(x not in known for x in ids):raise ValueError('所选窗口已失效，请刷新窗口列表')
 registered={c['window_id'] for c in channels}
 return sorted({c['gm'] for c in channels if c['window_id'] in ids})
