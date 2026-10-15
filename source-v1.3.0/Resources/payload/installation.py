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
 except Exception:bit={'ok':False,'message':'请安装并登录比特浏览器，在设置中开启 Local API（端口 54345），然后重新检测。'}
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

def initialize(window_ids=None):
 # Discovery and permissions already use exclusive guards and do not publish.
 if window_ids is not None:
  from window_scope import select_windows
  select_windows(fetch_all(),window_ids)
 for script in ('onboard_windows.py','probe_all_channels.py'):
  cmd=[sys.executable,'-u',str(ROOT/script)]
  for wid in window_ids or []:cmd.extend(['--window-id',wid])
  subprocess.run(cmd,cwd=ROOT,check=True)
 print('本机执行流程已安装，频道配置完成。未就绪频道请查看具体原因；本次不会发布视频。',flush=True)

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
