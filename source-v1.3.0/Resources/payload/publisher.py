"""Local authoritative ledger. No automatic retry of an upload."""
import sqlite3,json,hashlib,uuid,argparse
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
ROOT=Path(__file__).parent
TZ=ZoneInfo('Asia/Taipei')
ACTIVE=('上传中','填写中','检查中','发布中','结果待核查')
class Ledger:
 def __init__(self,path=ROOT/'publisher.sqlite3'):
  self.db=sqlite3.connect(path,timeout=30,isolation_level=None);self.db.row_factory=sqlite3.Row
  self.db.executescript('''PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS channels(id TEXT PRIMARY KEY,gm TEXT NOT NULL,name TEXT,window_id TEXT,enabled INTEGER DEFAULT 0,verified INTEGER DEFAULT 0,last_publish TEXT,reason TEXT);
CREATE TABLE IF NOT EXISTS assets(sha TEXT PRIMARY KEY,payload TEXT NOT NULL,complete INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,channel TEXT NOT NULL REFERENCES channels(id),day TEXT NOT NULL,ordinal INTEGER,sha TEXT UNIQUE REFERENCES assets(sha),state TEXT NOT NULL,token TEXT,url TEXT,published TEXT,error TEXT,UNIQUE(channel,day));
CREATE TABLE IF NOT EXISTS logs(id TEXT PRIMARY KEY,task TEXT,stage TEXT,start TEXT,end TEXT,error TEXT,screenshot TEXT,recovery TEXT);
CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT,key TEXT,done INTEGER DEFAULT 0);
DROP INDEX IF EXISTS one_upload;
''')
  columns={r[1] for r in self.db.execute('PRAGMA table_info(tasks)')}
  if 'mode' not in columns:self.db.execute("ALTER TABLE tasks ADD COLUMN mode TEXT NOT NULL DEFAULT 'draft'")
  if 'manual' not in columns:self.db.execute('ALTER TABLE tasks ADD COLUMN manual INTEGER NOT NULL DEFAULT 0')
  if 'run_window' not in columns:self.db.execute('ALTER TABLE tasks ADD COLUMN run_window TEXT')
  self.db.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_upload_per_window ON tasks(run_window) WHERE state IN ('上传中','填写中','检查中','发布中','结果待核查')")
 def queue(self,kind,key):self.db.execute('INSERT INTO outbox(kind,key) VALUES(?,?)',(kind,key))
 def channel(self,id,gm,name,window_id='',enabled=False,verified=False,reason='待核实实际频道、登录及长视频权限'):
  with self.tx():
   self.db.execute('INSERT INTO channels(id,gm,name,window_id,enabled,verified,reason) VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET gm=excluded.gm,name=excluded.name,window_id=excluded.window_id,enabled=excluded.enabled,verified=excluded.verified,reason=excluded.reason',(id,gm,name,window_id,enabled,verified,reason));self.queue('channels',id)
 def tx(self):
  from contextlib import contextmanager
  @contextmanager
  def transaction():
   self.db.execute('BEGIN IMMEDIATE')
   try:yield;self.db.execute('COMMIT')
   except BaseException:self.db.execute('ROLLBACK');raise
  return transaction()
 def scan(self,items):
  from scan_materials import completeness_errors
  seen=set()
  for p in items:
   v=Path(p['video']); before=v.stat();h=hashlib.sha256()
   with v.open('rb') as f:
    for block in iter(lambda:f.read(8*1024*1024),b''):h.update(block)
   after=v.stat()
   if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):raise ValueError('视频在哈希计算期间改变')
   sha=h.hexdigest(); seen.add(sha); reasons=completeness_errors(p); complete=not reasons
   p={**p,'sha256':sha,'video_size':after.st_size,'video_mtime_ns':after.st_mtime_ns,'missing_reasons':reasons,'available':True}
   with self.tx():
    self.db.execute('INSERT INTO assets VALUES(?,?,?) ON CONFLICT(sha) DO UPDATE SET payload=excluded.payload,complete=excluded.complete',(sha,json.dumps(p,ensure_ascii=False),complete));self.queue('assets',sha)
   print('扫描',v.name,sha[:12], '完整' if complete else '不完整：'+'；'.join(reasons),flush=True)
  # Retain task history; withdraw only unassigned assets absent from this scan.
  with self.tx():
   for row in self.db.execute('SELECT sha,payload FROM assets WHERE sha NOT IN (SELECT sha FROM tasks WHERE sha IS NOT NULL)').fetchall():
    if row['sha'] not in seen:
     payload=json.loads(row['payload']);payload.update(available=False,missing_reasons=['不在本次扫描结果中，请检查当前素材目录'])
     self.db.execute('UPDATE assets SET complete=0,payload=? WHERE sha=?',(json.dumps(payload,ensure_ascii=False),row['sha']));self.queue('assets',row['sha'])
 def refresh_materials(self,items):
  from scan_materials import completeness_errors
  by_path={p['video']:p for p in items};updated=0;skipped=0
  with self.tx():
   rows=self.db.execute('SELECT sha,payload FROM assets WHERE sha NOT IN (SELECT sha FROM tasks WHERE sha IS NOT NULL)').fetchall()
   for row in rows:
    old=json.loads(row['payload']);item=by_path.get(old['video'])
    if not item:continue
    stat=Path(item['video']).stat()
    if (old.get('video_size'),old.get('video_mtime_ns'))!=(stat.st_size,stat.st_mtime_ns):
     skipped+=1;old['missing_reasons']=['视频已变更，请重新扫描素材'];self.db.execute('UPDATE assets SET complete=0,payload=? WHERE sha=?',(json.dumps(old,ensure_ascii=False),row['sha']));self.queue('assets',row['sha']);continue
    reasons=completeness_errors(item)
    payload={**old,**item,'missing_reasons':reasons,'available':True}
    self.db.execute('UPDATE assets SET payload=?,complete=? WHERE sha=?',(json.dumps(payload,ensure_ascii=False),not reasons,row['sha']))
    self.queue('assets',row['sha']);updated+=1
  print('已刷新 '+str(updated)+' 条未分配素材的文案；已创建任务保持原文案。'+('有 '+str(skipped)+' 条视频已变更，请重新扫描。' if skipped else ''),flush=True)
  return updated
 def plan(self,day,gms=None):
  with self.tx():
   cs=self.db.execute('SELECT * FROM channels WHERE enabled=1 AND verified=1 ORDER BY COALESCE(last_publish,\'\'),gm,id').fetchall()
   if gms is not None:cs=[c for c in cs if c['gm'] in gms]
   seq=self.db.execute('SELECT COALESCE(MAX(ordinal),0) FROM tasks WHERE day=?',(day,)).fetchone()[0]
   for c in cs:
    prior=self.db.execute('SELECT * FROM tasks WHERE channel=? AND day=?',(c['id'],day)).fetchone()
    if prior and prior['state']!='缺素材':continue
    if self.db.execute("SELECT 1 FROM tasks WHERE channel=? AND state IN ('待执行','上传中','填写中','检查中','发布中','草稿','结果待核查','异常待处理')",(c['id'],)).fetchone():continue
    a=self.db.execute('SELECT sha FROM assets WHERE complete=1 AND sha NOT IN (SELECT sha FROM tasks WHERE sha IS NOT NULL) ORDER BY sha LIMIT 1').fetchone()
    seq+=1;key=prior['id'] if prior else uuid.uuid4().hex
    if prior:self.db.execute('UPDATE tasks SET sha=?,state=?,ordinal=? WHERE id=?',(a[0] if a else None,'待执行' if a else '缺素材',seq,key))
    else:self.db.execute('INSERT INTO tasks(id,channel,day,ordinal,sha,state) VALUES(?,?,?,?,?,?)',(key,c['id'],day,seq,a[0] if a else None,'待执行' if a else '缺素材'))
    self.queue('tasks',key)
 def claim(self,now=None,gms=None,manual=False,mode="draft",schedule_window=None,concurrency=1,task_ids=None):
  from parallel_settings import validate
  validate(concurrency)
  now=(now or datetime.now(TZ)).astimezone(TZ)
  if mode not in ("draft","public"):raise ValueError("发布类型无效")
  if not manual:
   from schedule_settings import in_window
   if not in_window(now,schedule_window or {'start':'10:00','end':'18:00'}):return None
  with self.tx():
   if self.db.execute("SELECT count(*) FROM tasks WHERE state IN ('上传中','填写中','检查中','发布中')").fetchone()[0]>=concurrency:return None
   scope='' if gms is None else ' AND c.gm IN ('+','.join('?' for _ in gms)+')'
   task_scope='' if task_ids is None else (' AND t.id IN ('+','.join('?' for _ in task_ids)+')' if task_ids else ' AND 0')
   date_scope='t.day<=?' if manual and task_ids is not None else 't.day=?'
   t=self.db.execute("SELECT t.* FROM tasks t JOIN channels c ON c.id=t.channel WHERE "+date_scope+" AND NOT EXISTS (SELECT 1 FROM tasks done WHERE done.channel=t.channel AND done.state='已发布' AND substr(done.published,1,10)=? ) AND t.state='待执行' AND c.enabled=1 AND c.verified=1 AND NOT EXISTS (SELECT 1 FROM tasks busy JOIN channels bc ON bc.id=busy.channel WHERE busy.state IN ('上传中','填写中','检查中','发布中','结果待核查') AND (bc.window_id=c.window_id OR bc.gm=c.gm))"+scope+task_scope+" ORDER BY ordinal LIMIT 1",(now.date().isoformat(),now.date().isoformat(),*(gms or []),*(task_ids or []))).fetchone()
   if not t:return None
   p=json.loads(self.db.execute('SELECT payload FROM assets WHERE sha=?',(t['sha'],)).fetchone()[0])
   token=uuid.uuid4().hex;self.db.execute("UPDATE tasks SET state='上传中',token=?,mode=?,manual=?,run_window=(SELECT COALESCE(NULLIF(window_id,''),gm) FROM channels WHERE id=tasks.channel) WHERE id=?",(token,mode,int(manual),t['id']));self.queue('tasks',t['id'])
   return {**dict(t),**p,'token':token,'channel_id':t['channel'],'publish_enabled':mode=='public','mode':mode,'manual':manual,'visibility':'public' if mode=='public' else 'private'}
 def report(self,key,token,state,channel_id,url='',video_id='',public=False,error='',screenshot=''):
  allowed={'上传中':{'填写中','异常待处理','结果待核查'},'填写中':{'检查中','异常待处理','结果待核查'},'检查中':{'发布中','草稿','异常待处理','结果待核查'},'发布中':{'已发布','结果待核查','异常待处理'}}
  with self.tx():
   t=self.db.execute('SELECT * FROM tasks WHERE id=?',(key,)).fetchone()
   if not t or token!=t['token']:raise ValueError('无效任务凭据')
   if channel_id!=t['channel']:raise ValueError('错频道，停止')
   if state not in allowed.get(t['state'],set()):raise ValueError('非法状态迁移')
   if state=='已发布' and (t['mode']!='public' or not public or not video_id or url not in ('https://www.youtube.com/watch?v='+video_id,'https://youtu.be/'+video_id)):raise ValueError('缺少公开状态和视频链接证据')
   now=datetime.now(TZ).isoformat();self.db.execute('UPDATE tasks SET state=?,url=?,error=?,published=? WHERE id=?',(state,url or t['url'],error,now if state=='已发布' else t['published'],key))
   if state=='已发布':self.db.execute('UPDATE channels SET last_publish=? WHERE id=?',(now,t['channel']));self.queue('channels',t['channel'])
   lid=uuid.uuid4().hex;self.db.execute('INSERT INTO logs VALUES(?,?,?,?,?,?,?,?)',(lid,key,state,now,now,error,screenshot,''));self.queue('logs',lid);self.queue('tasks',key)
 def recover(self):
  with self.tx():
   for t in self.db.execute("SELECT id FROM tasks WHERE state IN ('上传中','填写中','检查中','发布中')").fetchall():
    self.db.execute("UPDATE tasks SET state='结果待核查',error='进程中断；先核查现有草稿及视频，禁止直接重传' WHERE id=?",(t['id'],));self.queue('tasks',t['id'])
 def snapshot(self):return {k:[dict(r) for r in self.db.execute('SELECT * FROM '+k)] for k in ('channels','assets','tasks','logs')}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('command',choices=['scan','plan','status','recover']);p.add_argument('--date',default=datetime.now(TZ).date().isoformat());p.add_argument('--gm',action='append');a=p.parse_args();l=Ledger()
 if a.command=='scan':l.scan(json.loads((ROOT/'素材任务清单.json').read_text()))
 elif a.command=='plan':l.plan(a.date,gms=a.gm)
 elif a.command=='recover':l.recover()
 else:print(json.dumps(l.snapshot(),ensure_ascii=False,indent=2))
