"""Read fresh Studio state for an exact task/video, without uploading or saving changes."""
import json,re,uuid
from publisher import ROOT,Ledger,datetime,TZ
from parallel_settings import task_path
from bit_runner import open_page
from channel_probe import wait
ACTIVE=('上传中','填写中','检查中','发布中')

def video_url(t):
 url=t.get('url') or ''
 if not url:
  path=task_path(t['id'],'checkpoint')
  if path.exists():url=json.loads(path.read_text()).get('video_url','')
 if not re.fullmatch(r'https://youtu\.be/[A-Za-z0-9_-]{11}',url):raise ValueError('尚未记录原视频 ID，请先核查原视频；不会按标题猜测')
 return url

def classify(e,url,channel):
 if e.get('url')!='https://studio.youtube.com/video/'+url.rsplit('/',1)[-1]+'/edit' or url not in e.get('links',[]):raise ValueError('原视频 ID 不匹配，保持台账原状态')
 if e.get('channel')!=channel:raise ValueError('实际频道不匹配，保持台账原状态')
 if e.get('dirty'):raise ValueError('检测页有未保存更改，无法确认实际状态')
 visibility=e.get('visibility','').strip()
 if e.get('draft'):return '草稿','draft'
 if visibility in ('Public','公开','公開','Công khai'):return '已发布','public'
 if visibility in ('Private','私享','私密','不公开','私人','Riêng tư'):return '草稿','draft'
 if visibility in ('Unlisted','不公开列出','非公開','Không công khai'):return '未列出','draft'
 raise ValueError('尚不能确认平台可见性：'+visibility+'，保持台账原状态')

def inspect(t,url):
 b=tid=c=None
 try:
  b,tid,c=open_page(t['window_id'])
  c.call('Page.navigate',{'url':'https://studio.youtube.com/channel/'+t['channel']+'/videos/upload'})
  actual=wait(c,"[...document.querySelectorAll('a[href]')].map(e=>e.href).find(u=>u.startsWith('https://studio.youtube.com/channel/UC'))",timeout=25)
  if actual.split('/channel/')[1].split('/')[0]!=t['channel']:raise ValueError('实际频道不匹配，请在比特窗口切换到目标频道再刷新')
  try:wait(c,"document.querySelectorAll('ytcp-video-row').length>0 || /No content|没有内容|無內容|Không có nội dung/.test(document.body.innerText)",timeout=15)
  except ValueError:pass
  expected='https://studio.youtube.com/video/'+url.rsplit('/',1)[-1]+'/edit'
  row=c.evaluate("(()=>{const expected="+json.dumps(expected)+";const row=[...document.querySelectorAll('ytcp-video-row')].find(e=>[...e.querySelectorAll('a[href]')].some(a=>a.href===expected));if(!row)return null;const visibility=row.querySelector('.tablecell-visibility')?.innerText.trim()||'';return {url:expected,links:["+json.dumps(url)+"],channel:"+json.dumps(t['channel'])+",visibility,draft:/^(Draft|草稿|Bản nháp)$/.test(visibility),dirty:false,warning:/Partially blocked|部分.*屏蔽|部分.*封鎖/i.test(row.innerText)?'平台显示部分地区屏蔽，请查看 YouTube 版权限制详情':''}})()")
  if row:return row
  c.call('Page.navigate',{'url':'https://studio.youtube.com/video/'+url.rsplit('/',1)[-1]+'/edit'})
  wait(c,"document.body.innerText.includes("+json.dumps(url)+") && (document.querySelector('#visibility-text')||[...document.querySelectorAll('button')].some(e=>/^(Edit draft|编辑草稿|編輯草稿|Chỉnh sửa bản nháp)$/.test(e.innerText.trim())))",timeout=60)
  return c.evaluate("({url:location.href,links:[...document.querySelectorAll('a[href]')].map(e=>e.href).concat([...document.querySelectorAll('*')].filter(e=>e.children.length===0&&e.textContent.trim().startsWith('https://youtu.be/')).map(e=>e.textContent.trim())),channel:([...document.querySelectorAll('a[href]')].map(e=>e.href).find(u=>u.startsWith('https://studio.youtube.com/channel/UC'))||'').split('/channel/')[1]?.split('/')[0]||'',visibility:document.querySelector('#visibility-text')?.innerText||'',draft:[...document.querySelectorAll('button')].some(e=>/^(Edit draft|编辑草稿|編輯草稿|Chỉnh sửa bản nháp)$/.test(e.innerText.trim())),dirty:[...document.querySelectorAll('button')].some(e=>/^(Save|保存|儲存|Lưu)$/.test(e.innerText.trim())&&!e.disabled),warning:/Partially blocked|部分.*屏蔽|部分.*封鎖/i.test(document.body.innerText)?'平台显示部分地区屏蔽，请查看 YouTube 版权限制详情':''})")
 finally:
  if c:
   try:c.close()
   except Exception:pass
  if b:
   try:
    if tid:b.call('Target.closeTarget',{'targetId':tid})
   except Exception:pass
   try:b.close()
   except Exception:pass

def _refresh(task,probe=inspect):
 if (ROOT/'.update-lock').exists():raise ValueError('正在更新，暂不能核查')
 l=Ledger()
 try:
  t=l.db.execute('SELECT t.*,c.window_id,c.gm FROM tasks t JOIN channels c ON c.id=t.channel WHERE t.id=?',(task,)).fetchone()
  if not t:raise ValueError('任务不存在')
  t=dict(t)
  if t['state'] in ACTIVE:raise ValueError('此任务仍在自动执行，请先停止或等待完成')
  if l.db.execute("SELECT 1 FROM tasks other JOIN channels c ON c.id=other.channel WHERE other.id!=? AND other.state IN ('上传中','填写中','检查中','发布中') AND (c.window_id=? OR c.gm=?)",(task,t['window_id'],t['gm'])).fetchone():raise ValueError('该窗口正在执行其他任务，暂不切换频道')
  url=video_url(t);e=probe(t,url);state,mode=classify(e,url,t['channel']);now=datetime.now(TZ).isoformat()
  with l.tx():
   current=l.db.execute('SELECT token,state FROM tasks WHERE id=?',(task,)).fetchone()
   if current['token']!=t['token'] or current['state']!=t['state']:raise ValueError('检测期间任务状态已改变，请重新刷新')
   published=(t['published'] or now) if state=='已发布' else t['published']
   l.db.execute('UPDATE tasks SET state=?,mode=?,url=?,error=?,published=? WHERE id=?',(state,mode,url,e.get('warning',''),published,task));l.queue('tasks',task)
   if state=='已发布':l.db.execute('UPDATE channels SET last_publish=? WHERE id=?',(published,t['channel']));l.queue('channels',t['channel'])
   key=uuid.uuid4().hex;l.db.execute('INSERT INTO logs VALUES(?,?,?,?,?,?,?,?)',(key,task,'刷新平台状态',now,now,'','',json.dumps({'before':t['state'],'state':state,'url':url,'visibility':e.get('visibility'),'warning':e.get('warning',''),'published_time_source':'首次核实时间；平台实际发布时间未读取'},ensure_ascii=False)));l.queue('logs',key)
  return {'ok':True,'state':state,'url':url,'message':'已从 Studio 重新核实：'+state}
 finally:l.db.close()

def refresh(task,probe=inspect):
 import socket
 from contextlib import ExitStack
 with ExitStack() as stack:
  for port in (18742,18744):
   sock=stack.enter_context(socket.socket())
   try:sock.bind(('127.0.0.1',port))
   except OSError:raise ValueError('正在配置频道或启动任务，请稍后刷新状态')
  return _refresh(task,probe)
