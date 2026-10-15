"""Install a signature-verified staged app, preserving per-user state. No shell commands."""
import argparse,contextlib,json,os,posixpath,plistlib,shutil,signal,socket,sqlite3,subprocess,time,urllib.request,zipfile
from pathlib import Path
ACTIVE=('上传中','填写中','检查中','发布中')

def busy(root,port):
 db=root/'publisher.sqlite3'
 if db.exists():
  with sqlite3.connect(f'file:{db}?mode=ro',uri=True,timeout=3) as conn:
   if conn.execute('SELECT 1 FROM tasks WHERE state IN (?,?,?,?)',ACTIVE).fetchone():return True
 try:
  with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/status',timeout=3) as response:
   state=json.load(response)
  return bool(state.get('job',{}).get('running'))
 except Exception:return False

def services(root):
 text=subprocess.check_output(['/bin/ps','-axo','pid=,command='],text=True)
 found=[]
 for line in text.splitlines():
  row=line.strip().split(None,1)
  if len(row)!=2:continue
  # Exact final script argument and mode. Never terminate another workspace's services.
  if any(row[1].endswith(str(base/script)+' '+mode) for base in (root,root.resolve()) for script,mode in [('dashboard.py','--serve'),('bridge.py','serve')]):found.append(int(row[0]))
 return found

def extract(archive,stage,version):
 with zipfile.ZipFile(archive) as z:
  total=0;links={}
  for item in z.infolist():
   path=Path(item.filename)
   if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0]!='YouTube发布工作台.app':raise ValueError('更新包目录不合法')
   if (item.external_attr>>16)&0o170000==0o120000:
    target=z.read(item).decode('utf-8');normalized=posixpath.normpath(posixpath.join(str(path.parent),target))
    if target.startswith('/') or not normalized.startswith('YouTube发布工作台.app/'):raise ValueError('更新包符号链接越界')
    links[item.filename]=target
   total+=item.file_size
   if total>2_000_000_000:raise ValueError('更新包超过大小限制')
  for item in z.infolist():
   if any(str(parent) in links for parent in Path(item.filename).parents):raise ValueError('更新包写入符号链接目录')
  for item in z.infolist():
   p=stage/item.filename
   if item.filename in links:continue
   if item.is_dir():p.mkdir(parents=True,exist_ok=True);continue
   p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(z.read(item));p.chmod((item.external_attr>>16)&0o777 or 0o644)
  for name,target in links.items():
   p=stage/name;p.parent.mkdir(parents=True,exist_ok=True);p.symlink_to(target)
 app=stage/'YouTube发布工作台.app'
 info=plistlib.loads((app/'Contents/Info.plist').read_bytes())
 if info.get('CFBundleIdentifier')!='local.ypp.publisher' or info.get('CFBundleShortVersionString')!=version:raise ValueError('更新包应用身份或版本不匹配')
 subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(app)],check=True,capture_output=True)
 return app

def backup(root,target):
 target.mkdir(parents=True,exist_ok=False)
 db=root/'publisher.sqlite3'
 if db.exists():
  with sqlite3.connect(db) as source,sqlite3.connect(target/db.name) as dest:source.backup(dest)
 for p in root.glob('*.json'):shutil.copy2(p,target/p.name)
 (target/'恢复说明.txt').write_text('配置和台账快照仅用于人工恢复。不要直接覆盖已有后续发布记录，否则会影响去重。旧应用保存在相邻的 .previous.app。')

def terminate(pids):
 for pid in pids:
  try:os.kill(pid,signal.SIGTERM)
  except ProcessLookupError:pass
 for _ in range(100):
  alive=[]
  for pid in pids:
   try:os.kill(pid,0);alive.append(pid)
   except ProcessLookupError:pass
  if not alive:return
  time.sleep(.1)
 raise ValueError('后台服务未正常退出，已取消替换')

def exists(pid):
 try:os.kill(pid,0);return True
 except ProcessLookupError:return False

def run(args):
 root=Path(args.data).absolute();destination=Path(args.app).resolve();cache=Path(args.cache).resolve()
 root.mkdir(parents=True,exist_ok=True);cache.mkdir(parents=True,exist_ok=True)
 statefile=cache/'install-state.json'
 def state(status,message):
  temp=statefile.with_suffix('.tmp');temp.write_text(json.dumps({'status':status,'message':message},ensure_ascii=False));temp.replace(statefile)
 lock=root/'.update-lock';owned=False;swapped=False;stopped=False;old=None
 try:
  if not os.access(destination.parent,os.W_OK):raise ValueError('应用目录不可写，请将应用放到当前用户可写的 Applications 文件夹，或手动安装新版')
  with socket.socket() as s:
   if s.connect_ex(('127.0.0.1',args.port))==0 and not services(root):raise ValueError('当前端口由另一工作台占用，请关闭旧工作台后更新')
  if lock.exists():raise ValueError('已有更新正在运行；如上次异常中断，请查看更新日志')
  lock.mkdir();owned=True
  stage=cache/'staged';stage.mkdir(exist_ok=True)
  staged=extract(Path(args.archive),stage,args.version)
  state('waiting','新版已下载校验，等待当前操作完成。更新期间暂停启动新任务。')
  with contextlib.ExitStack() as stack:
   deadline=time.time()+86400
   while True:
    if not exists(args.parent):raise ValueError('应用已关闭，取消本次更新；请重新打开后检查更新')
    if time.time()>deadline:raise ValueError('等待任务结束超过 24 小时，请稍后重试')
    if busy(root,args.port):time.sleep(3);continue
    held=[]
    try:
     for port in (18742,18744):
      s=socket.socket();held.append(s);s.bind(('127.0.0.1',port))
     if busy(root,args.port):raise BlockingIOError()
    except OSError:
     for s in held:s.close()
     time.sleep(3);continue
    for s in held:stack.enter_context(s)
    break
   state('ready','准备重启并安装更新')
   until=time.time()+30
   while exists(args.parent):
    if time.time()>until:raise ValueError('应用未退出，取消本次更新')
    time.sleep(.2)
   pids=services(root);terminate(pids);stopped=True
   if busy(root,args.port):raise ValueError('仍有上传任务，取消替换')
   snapshot=root/'更新备份'/time.strftime('%Y%m%d-%H%M%S');backup(root,snapshot)
   incoming=destination.parent/(destination.stem+'.incoming.app')
   old=destination.parent/(destination.stem+'.previous.app')
   if incoming.exists():shutil.rmtree(incoming)
   shutil.copytree(staged,incoming,symlinks=True)
   if old.exists():shutil.rmtree(old)
   destination.rename(old)
   try:incoming.rename(destination);swapped=True
   except Exception:old.rename(destination);raise
   env={**os.environ,'YPP_APP_DATA':str(root),'YPP_DASHBOARD_PORT':str(args.port),'PYTHONDONTWRITEBYTECODE':'1','YPP_SKIP_UPDATE_CHECK':'1'}
   arch='arm64' if __import__('platform').machine()=='arm64' else 'x86_64'
   res=destination/'Contents/Resources'
  # Release guards only after app replacement. New service starts using the preserved state.
  lock.rmdir();owned=False
  result=subprocess.run([str(res/'runtime'/arch/'python/bin/python3'),str(res/'bootstrap.py')],env=env,capture_output=True,text=True,timeout=45)
  if result.returncode!=0:raise ValueError('新版启动验证失败：'+result.stdout+result.stderr)
  state('complete','更新已安装；旧版和数据备份已保留')
  subprocess.Popen([str(destination/'Contents/MacOS/YouTubePublisher')],env=env,start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 except Exception as exc:
  message=str(exc)
  if swapped and old and old.exists():
   try:
    terminate(services(root));shutil.rmtree(destination);old.rename(destination)
    # Restore old code only; retain the authoritative ledger, which may contain later results.
    payload=destination/'Contents/Resources/payload'
    for source in payload.rglob('*'):
     if source.is_file():
      target=root/source.relative_to(payload);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    message+='；已恢复旧应用'
   except Exception as restore:message+='；恢复失败：'+str(restore)
  state('error',message)
  if stopped and destination.exists():
   if owned:lock.rmdir();owned=False
   subprocess.Popen([str(destination/'Contents/MacOS/YouTubePublisher')],env={**os.environ,'YPP_APP_DATA':str(root),'YPP_DASHBOARD_PORT':str(args.port),'YPP_SKIP_UPDATE_CHECK':'1'},start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  return 1
 finally:
  if owned:lock.rmdir()
 return 0

if __name__=='__main__':
 parser=argparse.ArgumentParser()
 for name in ('data','app','cache','archive','version'):parser.add_argument('--'+name,required=True)
 parser.add_argument('--parent',type=int,required=True);parser.add_argument('--port',type=int,default=18741)
 raise SystemExit(run(parser.parse_args()))
