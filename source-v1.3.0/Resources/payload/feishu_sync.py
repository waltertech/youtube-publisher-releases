"""Idempotent cloud projection; never invokes browser or upload."""
import json
from feishu_setup import call,setup,save,ROOT
from publisher import Ledger
NAMES={'channels':'频道配置','assets':'素材库','tasks':'发布计划','logs':'执行日志'}
KEYS={'channels':'频道ID','assets':'素材ID','tasks':'任务ID','logs':'日志ID'}
def projection(l,kind,r):
 if kind=='channels':return {'频道ID':r['id'],'GM窗口':r['gm'],'频道名称':r['name'],'主页':'https://www.youtube.com/channel/'+r['id'],'窗口ID':r['window_id'],'启用':bool(r['enabled']),'已核实可用':bool(r['verified']),'登录与验证状态':'已核实' if r['verified'] else '待核实','停用原因':r['reason'],**({'最近发布时间':r['last_publish']} if r['last_publish'] else {})}
 if kind=='assets':
  p=json.loads(r['payload']);t=l.db.execute('SELECT channel FROM tasks WHERE sha=?',(r['sha'],)).fetchone();return {'素材ID':r['sha'],'视频SHA256':r['sha'],'视频路径':p['video'],'封面路径':p.get('thumbnail') or '', '文案路径':p.get('copy_file') or '', '标题':p.get('title') or '', '完整':bool(r['complete']),'使用状态':['已占用' if t else '可分配' if r['complete'] else '不完整'],'分配频道':t[0] if t else ''}
 if kind=='tasks':
  gm=l.db.execute('SELECT gm FROM channels WHERE id=?',(r['channel'],)).fetchone()[0];return {'任务ID':r['id'],'素材ID':r['sha'] or '', '频道ID':r['channel'],'GM窗口':gm,'计划日期':r['day']+' 10:00','计划顺序':r['ordinal'],'执行状态':[r['state']],'视频链接':r['url'] or '','失败原因':r['error'] or '',**({'实际发布时间':r['published']} if r['published'] else {})}
 return {'日志ID':r['id'],'任务ID':r['task'] or '', '执行阶段':r['stage'],'开始时间':r['start'],'结束时间':r['end'],'错误':r['error'] or '', '截图路径':r['screenshot'] or '', '恢复结果':r['recovery'] or ''}
def sync():
 import socket
 lock=socket.socket()
 try:lock.bind(('127.0.0.1',18743))
 except OSError:raise ValueError('已有飞书同步正在运行')
 c=setup();l=Ledger();folder=ROOT/'sync';folder.mkdir(exist_ok=True)
 # Read business keys before every write: retry after unknown create response finds the original.
 import os
 os.chdir(ROOT)
 for kind,name in NAMES.items():
  tid=c['tables'][name];call('field-list',base_token=c['base_token'],table_id=tid)
  file='sync/'+kind+'.ndjson'
  manifest=call('record-list',base_token=c['base_token'],table_id=tid,format='ndjson',output=file,overwrite='true')
  if manifest['has_more']:raise ValueError('超过2000条，需分页同步；禁止用不完整键集创建重复记录')
  rows=[json.loads(s) for s in Path(file).read_text().splitlines() if s.strip()];index={r[KEYS[kind]]:r['record_id'] for r in rows}
  watermark=l.db.execute('SELECT COALESCE(MAX(id),0) FROM outbox WHERE kind=?',(kind,)).fetchone()[0]
  dirty={r[0] for r in l.db.execute('SELECT key FROM outbox WHERE kind=? AND done=0 AND id<=?',(kind,watermark))}
  snapshot=l.snapshot()[kind]
  for r in snapshot:
   key=r['sha'] if kind=='assets' else r['id']
   if key in index and key not in dirty:continue
   kw={'base_token':c['base_token'],'table_id':tid,'json':projection(l,kind,r)}
   if key in index:kw['record_id']=index[key]
   call('record-upsert',**kw)
  l.db.execute('UPDATE outbox SET done=1 WHERE kind=? AND id<=?',(kind,watermark))
 print('飞书状态同步完成')
from pathlib import Path
if __name__=='__main__':sync()
