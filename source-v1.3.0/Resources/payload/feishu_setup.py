import json,subprocess
from pathlib import Path
from publisher import ROOT,Ledger
from feishu_auth import CLI
CONFIG=ROOT/'飞书配置.json'
def call(command,**kw):
 args=[CLI,'base','+'+command,'--as','user']
 for k,v in kw.items():
  if k in ('overwrite','yes'):
   if v:args+=['--'+k]
   continue
  args+=['--'+k.replace('_','-'),json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else str(v)]
 r=subprocess.run(args,capture_output=True,text=True)
 if r.returncode:raise RuntimeError(r.stderr or r.stdout)
 x=json.loads(r.stdout)
 if x.get('manifest_version'):return x
 if not x.get('ok'):raise RuntimeError(x)
 return x['data']
def fields(texts,others=()):return [{'name':s,'type':'text'} for s in texts]+list(others)
def sel(n,opts):return {'name':n,'type':'select','options':[{'name':s} for s in opts]}
SCHEMAS={
'频道配置':fields(['频道ID','GM窗口','频道名称','主页','窗口ID','登录与验证状态','停用原因'],[{'name':'启用','type':'checkbox'},{'name':'已核实可用','type':'checkbox'},{'name':'最近发布时间','type':'datetime'}]),
'素材库':fields(['素材ID','视频SHA256','视频路径','封面路径','文案路径','标题','分配频道'],[{'name':'完整','type':'checkbox'},sel('使用状态',['可分配','不完整','已占用'])]),
'发布计划':fields(['任务ID','素材ID','频道ID','GM窗口','视频链接','失败原因'],[{'name':'计划日期','type':'datetime'},{'name':'计划顺序','type':'number'},{'name':'实际发布时间','type':'datetime'},sel('执行状态',['待执行','上传中','填写中','检查中','发布中','已发布','草稿','结果待核查','异常待处理','缺素材'])]),
'执行日志':fields(['日志ID','任务ID','执行阶段','错误','截图路径','恢复结果'],[{'name':'开始时间','type':'datetime'},{'name':'结束时间','type':'datetime'}])}
def save(c):CONFIG.write_text(json.dumps(c,ensure_ascii=False,indent=2))
def setup():
 from feishu_auth import require_owner
 owner=require_owner()
 c=json.loads(CONFIG.read_text()) if CONFIG.exists() else {'tables':{},'views':{},'records':{},'owner_id':owner['id']}
 if c.get('base'): c['base_token']=c['base']['base_token'];c['tables'].setdefault('频道配置',c['table']['id'])
 if not c.get('base_token'):
  d=call('base-create',name='YouTube 多频道发布管理',time_zone='Asia/Taipei',table_name='频道配置',fields=SCHEMAS['频道配置']);print(json.dumps(d,ensure_ascii=False),flush=True)
  c.update(d);save(c)
 # Native response may contain base metadata and initial table.
 for name,schema in SCHEMAS.items():
  if name not in c['tables']:
   d=call('table-create',base_token=c['base_token'],name=name,fields=schema);print(name,json.dumps(d,ensure_ascii=False),flush=True);c['tables'][name]=d.get('table',d)['id'];save(c)
 save(c);return c
if __name__=='__main__':setup()
