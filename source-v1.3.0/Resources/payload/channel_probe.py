"""Inspect Studio feature eligibility without uploading files or saving settings."""
import json,time,urllib.request
from file_adapter import CDP
from onboard_windows import api

def wait(c,expression,timeout=35):
 end=time.monotonic()+timeout
 while time.monotonic()<end:
  try:
   value=c.evaluate(expression)
   if value:return value
  except RuntimeError:pass
  time.sleep(.7)
 raise ValueError('频道页面未就绪，登录、网络或验证状态需要处理')

def inspect(w,channel):
 d=api('browser/open',{'id':w['id']});host=d['http'];host=host if host.startswith('http') else 'http://'+host
 b=CDP(d['ws']);tid=None;c=None
 try:
  tid=b.call('Target.createTarget',{'url':'https://www.youtube.com/channel_switcher'})['targetId']
  for _ in range(20):
   t=next((t for t in json.load(urllib.request.urlopen(host+'/json/list',timeout=8)) if t['id']==tid),None)
   if t:break
   time.sleep(.5)
  if not t:raise ValueError('检查页创建失败')
  c=CDP(t['webSocketDebuggerUrl'])
  wait(c,"document.querySelectorAll('ytd-account-item-renderer').length>0")
  selected=c.evaluate("[...document.querySelectorAll('ytd-account-item-renderer')].find(e=>e.data?.isSelected)?.data?.serviceEndpoint?.selectActiveIdentityEndpoint?.supportedTokens?.find(t=>t.offlineCacheKeyToken)?.offlineCacheKeyToken.clientCacheKey")
  target=channel['id'][2:]
  found=c.evaluate("(()=>{const e=[...document.querySelectorAll('ytd-account-item-renderer')].find(e=>e.data?.serviceEndpoint?.selectActiveIdentityEndpoint?.supportedTokens?.some(t=>t.offlineCacheKeyToken?.clientCacheKey==="+json.dumps(target)+"));if(!e)return false;if(!e.data.isSelected)e.click();return true})()")
  if not found:raise ValueError('目标频道不在当前账号的可切换列表中')
  if selected!=target:wait(c,"location.hostname==='www.youtube.com'&&!location.pathname.includes('channel_switcher')&&document.readyState==='complete'")
  c.call('Page.navigate',{'url':'https://studio.youtube.com/channel/'+channel['id']})
  actual=wait(c,"[...document.querySelectorAll('a[href]')].map(e=>e.href).find(x=>/^https:\\/\\/studio.youtube.com\\/channel\\/UC/.test(x))")
  if actual.split('/channel/')[1].split('/')[0]!=channel['id']:raise ValueError('Studio 实际频道与目标不符，尚未切换，停止权限核验')
  c.evaluate("document.querySelector('#dismiss-button')?.click()")
  wait(c,"!!document.querySelector('#settings-item')");c.evaluate("document.querySelector('#settings-item').click()")
  wait(c,"!!document.querySelector('ytcp-settings-dialog #channel')");c.evaluate("document.querySelector('ytcp-settings-dialog #channel').click()")
  wait(c,"document.querySelectorAll('ytcp-settings-dialog tp-yt-paper-tab').length===3");c.evaluate("document.querySelectorAll('ytcp-settings-dialog tp-yt-paper-tab')[2].click()")
  badges=wait(c,"(()=>{const bs=[...document.querySelectorAll('#page-features ytcp-badge')].map(e=>e.innerText.trim());return bs.length===3&&bs.every(Boolean)?bs:null})()")
  language=c.evaluate('document.documentElement.lang')
  enabled=badges[1] in ('Enabled','已启用','已啟用','Đã bật')
  return {'id':channel['id'],'name':channel['name'],'intermediate_enabled':enabled,'badges':badges,'language':language,'reason':'长视频和自定义封面权限已启用' if enabled else '中级功能未启用或状态语言尚未支持：'+badges[1]}
 finally:
  if c:
   try:
    if locals().get('selected') and selected!=locals().get('target'):
     c.call('Page.navigate',{'url':'https://www.youtube.com/channel_switcher'})
     wait(c,"document.querySelectorAll('ytd-account-item-renderer').length>0")
     c.evaluate("[...document.querySelectorAll('ytd-account-item-renderer')].find(e=>e.data?.serviceEndpoint?.selectActiveIdentityEndpoint?.supportedTokens?.some(t=>t.offlineCacheKeyToken?.clientCacheKey==="+json.dumps(selected)+"))?.click()")
     wait(c,"location.hostname==='www.youtube.com'&&!location.pathname.includes('channel_switcher')")
   finally:c.close()
  if tid:b.call('Target.closeTarget',{'targetId':tid})
  b.close()
if __name__=='__main__':
 import argparse
 from publisher import ROOT
 from bit_windows import fetch_all
 p=argparse.ArgumentParser();p.add_argument('--gm',required=True);a=p.parse_args()
 w=next(w for w in fetch_all() if w['name']==a.gm)
 report=json.loads((ROOT/'窗口接入状态.json').read_text());channels=report.get(w['id'],{}).get('channels',[])
 if not channels:
  from onboard_windows import discover
  channels=discover(w)
 rows=[]
 for ch in channels:
  try:row=inspect(w,ch)
  except Exception as e:row={**ch,'error':str(e)}
  rows.append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
 (ROOT/(a.gm+'权限核验.json')).write_text(json.dumps(rows,ensure_ascii=False,indent=2))
