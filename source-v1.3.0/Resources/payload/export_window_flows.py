"""Generate local per-window workflows; export files contain local bridge key."""
import json,re
from publisher import ROOT
from bit_windows import fetch_all

def export():
 import bridge
 base=json.loads((ROOT/'通用流程-无凭据.automa.json').read_text())
 folder=ROOT/'本机窗口流程';folder.mkdir(exist_ok=True,mode=0o700)
 rows=[]
 for w in fetch_all():
  flow=json.loads(json.dumps(base));flow['name']='YouTube发布-'+w['name']
  flow['globalData']=json.dumps({'gm':w['name'],'bridge_key':bridge.SECRET.read_text()},ensure_ascii=False)
  name=re.sub(r'[^\w.-]','_',w['name'])+'-'+w['id'][:8]+'.automa.json'
  p=folder/name;p.write_text(json.dumps(flow,ensure_ascii=False,indent=2));p.chmod(0o600)
  rows.append({'gm':w['name'],'window_id':w['id'],'flow_file':str(p),'binding_status':'待导入并绑定原生任务，不能视为已启用'})
 (ROOT/'本机窗口绑定清单.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
 print('已生成 '+str(len(rows))+' 个窗口的本机流程；原生任务绑定仍需核验。')
if __name__=='__main__':export()
