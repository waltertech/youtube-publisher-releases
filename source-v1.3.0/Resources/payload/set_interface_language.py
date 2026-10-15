"""Explicit maintenance command: set this browser's YouTube UI to English."""
import argparse,json,time
from publisher import ROOT
from bit_runner import open_page
from channel_probe import wait

def set_english(window_id):
 b,tid,c=open_page(window_id)
 try:
  c.call('Page.navigate',{'url':'https://www.youtube.com/'})
  wait(c,"!!document.querySelector('#avatar-btn')")
  c.evaluate("document.querySelector('#avatar-btn').click()")
  wait(c,"[...document.querySelectorAll('ytd-compact-link-renderer')].some(e=>/Ngôn ngữ hiển thị|Display language|Language:|语言|語言/.test(e.innerText))")
  c.evaluate("[...document.querySelectorAll('ytd-compact-link-renderer')].find(e=>/Ngôn ngữ hiển thị|Display language|Language:|语言|語言/.test(e.innerText)).click()")
  wait(c,"[...document.querySelectorAll('ytd-compact-link-renderer')].some(e=>e.innerText.trim()==='English (US)')")
  c.evaluate("[...document.querySelectorAll('ytd-compact-link-renderer')].find(e=>e.innerText.trim()==='English (US)').click()")
  wait(c,"document.documentElement.lang.startsWith('en')&&document.readyState==='complete'")
  print('YouTube 界面已切换为 English (US)',flush=True)
 finally:c.close();b.call('Target.closeTarget',{'targetId':tid});b.close()
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--gm',required=True);a=p.parse_args();w=next(w for w in json.loads((ROOT/'窗口接入状态.json').read_text()).values() if w['name']==a.gm);set_english(w['id'])
