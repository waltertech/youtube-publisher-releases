"""Per-user clean installation. Only shipped code is copied; user state is retained."""
import os,sys,json,shutil,subprocess,time,urllib.request,hashlib,socket,plistlib
from pathlib import Path
resources=Path(__file__).resolve().parent
root=Path(os.environ.get('YPP_APP_DATA',str(Path.home()/'Library/Application Support/YouTube发布工作台')))
port=int(os.environ.get('YPP_DASHBOARD_PORT','18741'))
root.mkdir(parents=True,exist_ok=True,mode=0o700)
logdir=root/'运行日志';logdir.mkdir(exist_ok=True)
url=f'http://127.0.0.1:{port}'
# Never reuse an older backend silently: the UI must match the installed version.
from runtime_upgrade import ensure_current_service
version=plistlib.loads((resources.parent/'Info.plist').read_bytes())['CFBundleShortVersionString']
try:
 if ensure_current_service(root,port,url,version):print(url,flush=True);sys.exit(0)
except Exception as exc:raise SystemExit(str(exc))
with socket.socket() as sock:
 if sock.connect_ex(('127.0.0.1',port))==0:raise SystemExit('工作台端口被其他程序占用，请关闭占用程序后重试。')
db=root/'publisher.sqlite3'
if db.exists():
 import sqlite3
 with sqlite3.connect(db) as conn:
  if conn.execute("SELECT 1 FROM tasks WHERE state IN ('上传中','填写中','检查中','发布中')").fetchone():raise SystemExit('检测到未结束的上传任务，请先核查旧任务，避免替换运行中的程序。')
lock=root/'.install-lock'
try:lock.mkdir()
except FileExistsError:raise SystemExit('初始化已在运行。如上次异常退出，请查看运行日志。')
try:
 for source in (resources/'payload').rglob('*'):
  if source.is_file():
   dst=root/source.relative_to(resources/'payload');dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dst)
 defaults={'调度配置.json':{'execution_engine':'local','draft_test_passed':True,'direct_public_approved':True,'local_public_enabled':True,'public_enabled':True,'native_tasks':{},'manual_ready':{},'timezone':'Asia/Taipei'},'本机配置.json':{},'定时设置.json':{'enabled':False,'start':'10:00','end':'18:00','mode':'draft','window_ids':[],'timezone':'Asia/Taipei'},'并行设置.json':{'concurrency':1}}
 for name,value in defaults.items():
  p=root/name
  if not p.exists():p.write_text(json.dumps(value,ensure_ascii=False,indent=2));p.chmod(0o600)
 env={**os.environ,'PYTHONPATH':str(resources/'vendor'),'SSL_CERT_FILE':str(resources/'vendor/certifi/cacert.pem'),'YPP_APP_RESOURCES':str(resources),'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1'}
 arch='arm64' if __import__('platform').machine()=='arm64' else 'x86_64'
 env['PATH']=str(resources/'tools'/arch)+':/usr/bin:/bin:/usr/sbin:/sbin'
 if '--init-only' in sys.argv:print(str(root));sys.exit(0)
 with socket.socket() as bridge_socket:
  bridge_free=bridge_socket.connect_ex(('127.0.0.1',18740))!=0
 if bridge_free:
  with (logdir/'bridge.log').open('ab') as log:subprocess.Popen([sys.executable,'-u',str(root/'bridge.py'),'serve'],cwd=root,env=env,stdout=log,stderr=log,start_new_session=True)
 with (logdir/'dashboard.log').open('ab') as log:subprocess.Popen([sys.executable,'-u',str(root/'dashboard.py'),'--serve'],cwd=root,env=env,stdout=log,stderr=log,start_new_session=True)
 for _ in range(60):
  try:
   with urllib.request.urlopen(url+'/health',timeout=1) as response:
    if json.load(response).get('service')=='ypp-dashboard':print(url,flush=True);break
  except Exception:time.sleep(.5)
 else:raise SystemExit('服务启动失败，请查看 ~/Library/Application Support/YouTube发布工作台/运行日志/dashboard.log')
finally:lock.rmdir()
