"""First-run checks and documented BitBrowser core repair. No account export."""
import json,subprocess,sys,os,socket
from pathlib import Path
from publisher import ROOT,Ledger
from bit_windows import fetch_all
from onboard_windows import api

def status():
 from feishu_auth import CLI
 try:
  windows=fetch_all();bit={'ok':True,'message':f'已连接比特浏览器，共 {len(windows)} 个窗口'}
 except Exception as e:bit={'ok':False,'message':'读取窗口失败：'+str(e)[:400]+'。请确认比特已登录，Local API 已开启（端口 54345）。'}
 return {'bit':bit,'python':sys.version.split()[0],'workflow':(ROOT/'通用流程-无凭据.automa.json').is_file(),'lark':Path(CLI).is_file(),'data_dir':str(ROOT),'native_import':'比特公开 API 未提供原生工作流导入接口。本应用已安装本机执行流程，无需设计器；附带模板供手动导入参考。'}

def repair_cores():
 # All repairs happen before discovery/uploads; never close a user-owned open profile.
 l=Ledger()
 try:
  if l.db.execute("SELECT 1 FROM tasks WHERE state IN ('上传中','填写中','检查中','发布中','结果待核查')").fetchone():raise ValueError('存在运行中或结果待核查任务，暂停内核修复')
 finally:l.db.close()
 report=[]
 for w in fetch_all():
  row={'window':w['name'],'status':'待检查'}
  try:
   detail=api('browser/detail',{'id':w['id']});old=str(detail.get('browserFingerPrint',{}).get('coreVersion',''))
   if not old.isdigit():row['status']='无法确认内核版本，请在比特设置中手动选择已安装内核'
   elif int(old)>=146:row['status']='已配置内核 '+old+'；将在频道发现时核验实际启动'
   elif api('browser/pids',{'ids':[w['id']]}).get(w['id']):row['status']='内核 '+old+'；窗口正在使用，请关闭后重试'
   else:
    api('browser/update/partial',{'ids':[w['id']],'browserFingerPrint':{'coreVersion':'146'}})
    try:
     d=api('browser/open',{'id':w['id']})
     if int(d.get('coreVersion','0').split('.')[0])<146:raise ValueError('返回内核版本仍低于兼容基线')
     api('browser/close',{'id':w['id']});row['status']='已切换并验证内核 '+str(d['coreVersion'])
    except Exception:
     try:api('browser/close',{'id':w['id']})
     except Exception:pass
     api('browser/update/partial',{'ids':[w['id']],'browserFingerPrint':{'coreVersion':old}})
     raise ValueError('自动切换失败，已恢复原配置。请在比特客户端安装 146 或更新内核，再重试。')
  except Exception as e:row['status']=str(e)
  report.append(row);print(w['name']+'：'+row['status'],flush=True)
 (ROOT/'安装检查结果.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))

def window_result(window_id):
 discovery_path=ROOT/'窗口接入状态.json'
 discovery=json.loads(discovery_path.read_text()) if discovery_path.exists() else {}
 row=discovery.get(window_id,{})
 if row.get('error'):return 0,row['error']
 if not row.get('channels'):return 0,'未发现频道，请检查 YouTube 登录、网络或验证页面'
 l=Ledger()
 try:
  channels=l.db.execute('SELECT enabled,verified,reason FROM channels WHERE window_id=?',(window_id,)).fetchall()
  count=sum(bool(c['enabled'] and c['verified']) for c in channels)
  reasons='；'.join(dict.fromkeys(c['reason'] or '权限未核实' for c in channels if not(c['enabled'] and c['verified'])))
  return count,reasons or '频道尚未完成绑定'
 finally:l.db.close()

def initialize(window_ids=None):
 from window_scope import select_windows
 windows=select_windows(fetch_all(),window_ids)
 if not windows:raise ValueError('比特接口已连接，但没有返回窗口。请确认新电脑登录的是拥有窗口权限的比特账号。')
 ready=0;failures=[]
 for index,w in enumerate(windows,1):
  prefix=f"[{index}/{len(windows)}] {w['name']}"
  try:
   for script,label in [('onboard_windows.py','发现频道'),('probe_all_channels.py','核验权限并启用')]:
    print(prefix+'：'+label,flush=True)
    subprocess.run([sys.executable,'-u',str(ROOT/script),'--window-id',w['id']],cwd=ROOT,check=True)
    if script=='onboard_windows.py':
     path=ROOT/'窗口接入状态.json'
     report=json.loads(path.read_text()) if path.exists() else {}
     row=report.get(w['id'],{})
     if row.get('error'):raise ValueError(row['error'])
   count,reason=window_result(w['id'])
   if not count:raise ValueError(reason)
   ready+=1;print(prefix+f'：配置完成，{count} 个可用频道',flush=True)
  except Exception as e:
   failures.append(prefix+'：'+str(e));print(failures[-1]+'；继续处理其他窗口',flush=True)
 summary=f'配置结束：{ready}/{len(windows)} 个窗口可用，{len(failures)} 个需处理。'
 if not ready:raise ValueError(summary+'\n'+'\n'.join(failures))
 print(summary+' 本次不会发布视频。',flush=True)

def configure_feishu(app_id,secret):
 from feishu_auth import CLI,refresh
 if not isinstance(app_id,str) or not app_id.startswith('cli_') or not isinstance(secret,str) or not secret:raise ValueError('请填写自己的飞书 App ID 和 App Secret')
 p=subprocess.run([CLI,'config','init','--app-id',app_id,'--app-secret-stdin','--brand','feishu'],input=secret+'\n',capture_output=True,text=True,timeout=45)
 if p.returncode:raise ValueError('飞书应用配置失败，请检查凭据和本机钥匙串权限')
 refresh();return {'ok':True}
if __name__=='__main__':
 if sys.argv[1:]==['repair']:
  from contextlib import ExitStack
  with ExitStack() as st:
   for port in (18742,18744):
    s=st.enter_context(socket.socket());s.bind(('127.0.0.1',port))
   repair_cores()
 else:
  import argparse
  p=argparse.ArgumentParser();p.add_argument('--window-id',action='append');a=p.parse_args();initialize(a.window_id)
