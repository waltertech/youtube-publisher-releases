"""Local BitBrowser runner. Reuses workflow page steps; no cloud workflow keys."""
import json,time,urllib.request,argparse,uuid
from publisher import ROOT,Ledger
from file_adapter import CDP,upload,prepare_publish,confirm_public,confirm_draft,page
from onboard_windows import api
from channel_probe import wait

def switch_channel(c,channel_id):
 c.call('Page.navigate',{'url':'https://www.youtube.com/channel_switcher'})
 wait(c,"document.querySelectorAll('ytd-account-item-renderer').length>0")
 result=c.evaluate("(()=>{const e=[...document.querySelectorAll('ytd-account-item-renderer')].find(e=>e.data?.serviceEndpoint?.selectActiveIdentityEndpoint?.supportedTokens?.some(t=>t.offlineCacheKeyToken?.clientCacheKey==="+json.dumps(channel_id[2:])+"));if(!e||e.data.isDisabled)return false;const selected=!!e.data.isSelected;if(!selected)e.click();return {selected}})()")
 if not result:raise ValueError('目标频道不在此窗口的可切换列表中')
 if not result['selected']:wait(c,"location.hostname==='www.youtube.com'&&!location.pathname.includes('channel_switcher')&&document.readyState==='complete'")
 c.call('Page.navigate',{'url':'https://studio.youtube.com/channel/'+channel_id})
 actual=wait(c,"[...document.querySelectorAll('a[href]')].map(e=>e.href).find(x=>/^https:\\/\\/studio.youtube.com\\/channel\\/UC/.test(x))")
 if actual.split('/channel/')[1].split('/')[0]!=channel_id:raise ValueError('实际频道不匹配，停止')
 lang=c.evaluate('document.documentElement.lang')
 if not (lang.startswith('en') or lang.startswith('zh')):raise ValueError('当前界面语言 '+lang+' 尚未通过上传适配验收；请在 YouTube 中切换为英文或简体中文后重试')
 c.evaluate("document.querySelector('#dismiss-button')?.click()")
 return lang

def open_page(window_id):
 d=api('browser/open',{'id':window_id});b=CDP(d['ws']);tid=b.call('Target.createTarget',{'url':'about:blank'})['targetId']
 host=d['http'];host=host if host.startswith('http') else 'http://'+host
 for _ in range(20):
  t=next((t for t in json.load(urllib.request.urlopen(host+'/json/list',timeout=8)) if t['id']==tid),None)
  if t:return b,tid,CDP(t['webSocketDebuggerUrl'])
  time.sleep(.5)
 b.call('Target.closeTarget',{'targetId':tid});b.close();raise ValueError('无法创建运行页')

def page_step(c,code,payload,variables,timeout):
 # Only material fields enter the website; task token and bridge secret stay local.
 public={k:v for k,v in payload.items() if k in ('channel_id','title','description','hashtags','tags','made_for_kids','ai_generated','publish_enabled','visibility','mode')}
 key='__ypp_'+uuid.uuid4().hex
 js="(()=>{const box=window["+json.dumps(key)+"]={done:false,vars:"+json.dumps(variables,ensure_ascii=False)+"};const payload="+json.dumps(public,ensure_ascii=False)+";const automaRefData=(a,b)=>b==='payload'?payload:box.vars[b];const automaSetVariable=(k,v)=>box.vars[k]=v;const automaNextBlock=()=>box.done=true;try{"+code+"}catch(e){box.error=e.message;box.done=true}})()"
 c.evaluate(js);end=time.monotonic()+timeout/1000
 while time.monotonic()<end:
  result=c.evaluate('window['+json.dumps(key)+']')
  if result and result.get('done'):
   c.evaluate('delete window['+json.dumps(key)+']')
   error=result.get('error') or result['vars'].get('last_error')
   if error:
    exception=ValueError(error);exception.variables=result['vars'];raise exception
   return result['vars']
  time.sleep(1)
 raise TimeoutError('页面步骤超时；需核查已有草稿，禁止重传')

def execute(task_id,preflight=False,resume=None):
 from parallel_settings import task_path,write
 path=task_path(task_id);l=Ledger();a=json.loads((path if path.exists() else ROOT/'.active-task.json').read_text())
 t=l.db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
 if not t or a['id']!=task_id or a['token']!=t['token'] or t['state'] not in (('上传中',) if resume is None else ('填写中','检查中','发布中')):raise ValueError('任务已失效')
 b=tid=c=None
 try:
  from task_control import register
  register(task_id,a['token'],a.get('target_id',''),a['window_id'])
  if resume is None:
   b,tid,c=open_page(a['window_id']);a['target_id']=tid;write(path,a);register(task_id,a['token'],tid,a['window_id']);lang=switch_channel(c,a['channel_id']);print('频道已核对；语言 '+lang,flush=True)
  else:
   if not 7<=resume<=19:raise ValueError('恢复位置无效，禁止重新上传视频')
   try:c=page(a,require_dialog=resume<19 or a['mode']=='draft')
   except Exception as e:raise ValueError('未找到原任务页面或频道身份不匹配；请在比特窗口核查原草稿/视频，不会重新上传。'+str(e)) from e
   checkpoint_file=task_path(task_id,'checkpoint')
   previous=json.loads(checkpoint_file.read_text()) if checkpoint_file.exists() else {}
   if resume<19:
    evidence=c.evaluate("({title:document.querySelector('ytcp-uploads-dialog #title-textarea #textbox')?.textContent||'',links:[...document.querySelectorAll('ytcp-uploads-dialog a[href]')].map(e=>e.href)})")
    expected=previous.get('video_url') or t['url']
    if expected and expected not in evidence.get('links',[]):raise ValueError('原视频 ID 不匹配，停止恢复')
    if not expected and evidence.get('title','').strip() not in (a.get('title','').strip(),__import__('pathlib').Path(a['video']).stem):raise ValueError('无法将原对话框与此素材关联，停止恢复')
   print('原任务页面与频道已核对；恢复步骤 '+str(resume)+'，禁止重复上传 video',flush=True)
  p={'key':a['id'],'token':a['token'],'channel_id':a['channel_id']};variables={'last_error':''}
  checkpoint_path=task_path(task_id,'checkpoint')
  if resume is not None and checkpoint_path.exists():variables={**json.loads(checkpoint_path.read_text()).get('variables',{}),'last_error':''}
  flow=json.loads((ROOT/'通用流程-无凭据.automa.json').read_text())
  for index,node in enumerate(flow['drawflow']['nodes']):
   if resume is not None and index<resume:continue
   d=node['data'];desc=d.get('description','')
   if d.get('disableBlock'):continue
   if node['label'] in ('trigger','new-tab'):continue
   phase=l.db.execute('SELECT state FROM tasks WHERE id=?',(task_id,)).fetchone()['state']
   # Capture the original video ID before a later timeout can close the dialog.
   video_url=''
   if index>=6:
    try:
     links=c.evaluate("[...document.querySelectorAll('ytcp-uploads-dialog a[href]')].map(e=>e.href)") or []
     video_url=next((u for u in links if __import__('re').fullmatch(r'https://youtu\.be/[A-Za-z0-9_-]{11}',u)),'')
    except Exception:pass
   if not video_url and checkpoint_path.exists():video_url=json.loads(checkpoint_path.read_text()).get('video_url','')
   write(checkpoint_path,{'node':index,'phase':phase,'variables':variables,'video_url':video_url})
   print(desc,flush=True)
   if d.get('context')=='website':
    code=d['code'].replace("e.innerText.trim()==='Music'","['Music','音乐','音樂'].includes(e.innerText.trim())")
    variables=page_step(c,code,a,variables,d.get('timeout',120000));continue
   if desc in ('仅领取调度器已锁定的输入','核查页面步骤错误'):continue
   if desc.startswith('原生路径上传 '):
    kind=desc.split()[-1]
    if resume is not None:
     prior=l.db.execute('SELECT state FROM file_submissions WHERE task=? AND kind=?',(task_id,kind)).fetchone()
     if prior:
      if prior['state']!='已提交':raise ValueError('文件提交结果不明确，请人工核查，禁止重传')
      print('已提交 '+kind+'，保留原文件，不重复提交',flush=True);continue
     if kind=='video':raise ValueError('恢复流程禁止重新上传视频')
    upload({**p,'kind':kind})
   elif desc.startswith('持久化状态：'):l.report(**p,state=desc.split('：')[1])
   elif desc=='正式发布前持久化授权和检查证据':
    if a['mode']=='public':prepare_publish(p)
   elif desc=='确认草稿或正式发布结果及视频ID':
    (confirm_public if a['mode']=='public' else confirm_draft)({**p,'public_selected':variables.get('public_selected') is True})
   else:raise ValueError('不支持的流程节点：'+desc)
 except Exception as e:
  if 'checkpoint_path' in locals() and hasattr(e,'variables'):
   checkpoint=json.loads(checkpoint_path.read_text());checkpoint['variables']=e.variables;write(checkpoint_path,checkpoint)
  current=l.db.execute('SELECT state FROM tasks WHERE id=?',(task_id,)).fetchone()
  if current and current['state'] in ('上传中','填写中','检查中','发布中'):l.report(task_id,a['token'],'结果待核查',a['channel_id'],error=str(e))
  raise
 finally:
  if c:c.close()
  if b:b.close()
  l.db.close()
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--task',required=True);p.add_argument('--resume',type=int);a=p.parse_args();execute(a.task,resume=a.resume)
