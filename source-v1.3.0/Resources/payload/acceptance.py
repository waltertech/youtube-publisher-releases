"""Unlock this runner only after the registered real draft test succeeds."""
import hashlib,json,threading
from publisher import ROOT,Ledger,datetime,TZ
PENDING=ROOT/'草稿验收任务.json'
FILES=('bit_runner.py','file_adapter.py','publisher.py','bridge.py','通用流程-无凭据.automa.json')
LOCK=threading.Lock()
def fingerprint():
 h=hashlib.sha256()
 for name in FILES:h.update(name.encode());h.update((ROOT/name).read_bytes())
 return h.hexdigest()
def register(task_id):
 l=Ledger()
 try:
  t=l.db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
  if not t or t['mode']!='draft' or t['state'] not in ('上传中','填写中','检查中'):raise ValueError('需要正在执行的草稿任务')
  value={'task_id':task_id,'channel':t['channel'],'sha':t['sha'],'fingerprint':fingerprint(),'status':'等待草稿完成'}
  PENDING.write_text(json.dumps(value,ensure_ascii=False,indent=2))
 finally:l.db.close()
def check():
 with LOCK:
  if not PENDING.exists():return
  p=json.loads(PENDING.read_text())
  if p.get('status')=='已通过':return
  if p['fingerprint']!=fingerprint():return
  l=Ledger()
  try:
   t=l.db.execute('SELECT * FROM tasks WHERE id=?',(p['task_id'],)).fetchone()
   if not t or t['state']!='草稿' or t['mode']!='draft' or t['channel']!=p['channel'] or t['sha']!=p['sha'] or not t['url']:return
   submitted={r[0] for r in l.db.execute("SELECT kind FROM file_submissions WHERE task=? AND state='已提交'",(t['id'],))}
   if submitted!={'video','thumbnail'}:return
   if not l.db.execute("SELECT 1 FROM logs WHERE task=? AND stage='草稿确认'",(t['id'],)).fetchone():return
   config_path=ROOT/'调度配置.json';cfg=json.loads(config_path.read_text())
   if cfg.get('execution_engine')!='local':return
   cfg.update(draft_test_passed=True,local_public_enabled=True,public_enabled=True,accepted_runner=p['fingerprint'],acceptance_task=t['id'],acceptance_url=t['url'])
   tmp=config_path.with_suffix('.acceptance.tmp');tmp.write_text(json.dumps(cfg,ensure_ascii=False,indent=2));tmp.replace(config_path)
   p.update(status='已通过',completed_at=datetime.now(TZ).isoformat(),url=t['url']);PENDING.write_text(json.dumps(p,ensure_ascii=False,indent=2))
  finally:l.db.close()
def state():
 if not PENDING.exists():return None
 p=json.loads(PENDING.read_text());return {k:p.get(k) for k in ('task_id','status','url','completed_at')}
