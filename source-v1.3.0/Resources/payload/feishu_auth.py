"""User-only authorization; never send device codes or tokens to the dashboard."""
import json,os,shutil,subprocess,threading,time,base64
from pathlib import Path
from publisher import ROOT
CLI=shutil.which('lark-cli') or str(Path.home()/'.local/bin/lark-cli')
LOCK=threading.Lock();CACHE={'authorized':False,'name':'','message':'正在检查飞书授权','url':'','qr':''};PENDING=None
SCOPES='base:app:create base:app:read base:table:create base:table:read base:field:create base:field:read base:record:create base:record:read base:record:update offline_access'
def cli(args,timeout=30):
 if not Path(CLI).is_file():raise ValueError('未安装飞书 CLI，请先在此电脑安装并配置 lark-cli')
 r=subprocess.run([CLI,*args],cwd=ROOT,capture_output=True,text=True,timeout=timeout,env={**os.environ,'LARKSUITE_CLI_NO_UPDATE_NOTIFIER':'1','LARKSUITE_CLI_NO_SKILLS_NOTIFIER':'1'})
 if r.returncode:raise ValueError('飞书操作失败：请检查本机CLI应用配置、授权或网络')
 return json.loads(r.stdout) if r.stdout.strip().startswith('{') else {}
def identity():
 x=cli(['auth','status','--json','--verify']);u=x.get('identities',{}).get('user',{})
 if not u.get('verified') or not u.get('openId'):raise ValueError('尚未授权或授权已失效，请先授权飞书账号')
 return {'id':u['openId'],'name':u.get('userName','飞书用户')}
def refresh():
 with LOCK:
  if PENDING:return
 try:
  u=identity()
  with LOCK:CACHE.update(authorized=True,name=u['name'],message='已授权：'+u['name'])
 except Exception as e:
  with LOCK:CACHE.update(authorized=False,name='',message=str(e))
def state():
 with LOCK:return dict(CACHE)
def loop():
 while True:refresh();time.sleep(60)
def begin():
 global PENDING
 x=cli(['auth','login','--scope',SCOPES,'--no-wait','--json']);d=x.get('data',x)
 url=d.get('verification_url') or d.get('verification_uri_complete');code=d.get('device_code')
 if not url or not code:raise ValueError('未取得飞书授权链接，请检查CLI配置')
 cli(['auth','qrcode',url,'--output','运行日志/feishu-auth.png'])
 qr='data:image/png;base64,'+base64.b64encode((ROOT/'运行日志/feishu-auth.png').read_bytes()).decode()
 with LOCK:
  PENDING=code;CACHE.update(authorized=False,url=url,qr=qr,message='请打开授权链接或扫码，完成后点击“我已授权”')
def finish():
 global PENDING
 with LOCK:code=PENDING
 if not code:raise ValueError('请先点击授权飞书，生成本次授权链接')
 cli(['auth','login','--device-code',code,'--json'],timeout=180)
 with LOCK:PENDING=None;CACHE.update(url='',qr='')
 refresh()
 if not state()['authorized']:raise ValueError('未确认授权成功，请重试')
def require_owner():
 u=identity();p=ROOT/'飞书配置.json'
 if p.exists():
  c=json.loads(p.read_text())
  if c.get('owner_id')!=u['id']:raise ValueError('当前飞书账号与此台账绑定账号不一致。请使用自己的独立台账配置，禁止同步到他人的台账。')
 return u
