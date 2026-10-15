"""Local daily schedule settings. Saving defaults never enables uploads."""
import json,re,threading
from datetime import datetime
from publisher import ROOT,TZ
PATH=ROOT/'定时设置.json'
LOCK=threading.RLock()
DEFAULT={'enabled':False,'start':'10:00','end':'18:00','mode':'draft','window_ids':[],'timezone':'Asia/Taipei'}
def read():
 with LOCK:return {**DEFAULT,**(json.loads(PATH.read_text()) if PATH.exists() else {})}
def validate(value):
 if not isinstance(value,dict):raise ValueError('设置格式无效')
 result={k:value.get(k,DEFAULT[k]) for k in DEFAULT};result['timezone']='Asia/Taipei'
 if type(result['enabled']) is not bool:raise ValueError('调度开关无效')
 for key in ('start','end'):
  if not isinstance(result[key],str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',result[key]):raise ValueError('时间格式应为 HH:MM')
 if result['start']>=result['end']:raise ValueError('结束时间必须晚于开始时间，暂不支持跨午夜')
 if result['mode'] not in ('draft','public'):raise ValueError('发布类型无效')
 ids=result['window_ids']
 if not isinstance(ids,list) or len(ids)>10000 or any(not isinstance(x,str) or not x or len(x)>128 for x in ids):raise ValueError('窗口选择无效')
 result['window_ids']=list(dict.fromkeys(ids))
 if result['enabled'] and not result['window_ids']:raise ValueError('启用定时调度前，请至少选择一个窗口')
 return result
def save(value):
 value=validate(value)
 with LOCK:
  tmp=PATH.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2));tmp.replace(PATH)
 return value
def in_window(now,settings):
 clock=now.astimezone(TZ).strftime('%H:%M')
 return settings['start']<=clock<settings['end']
def blockers(config,settings):
 result=[]
 if not config.get('draft_test_passed'):result.append('完整草稿验收尚未通过')
 if config.get('execution_engine')!='local' and not config.get('bindings_verified'):result.append('原生任务窗口绑定尚未核实')
 if settings['mode']=='public' and (not config.get('public_enabled') or (config.get('execution_engine')=='local' and not config.get('local_public_enabled'))):result.append('正式发布尚未开放')
 return result
