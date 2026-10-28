"""Safe first-run configuration: never starts publishing."""
import argparse,json,sys
from pathlib import Path
from publisher import ROOT,Ledger

def configure(material_dir):
 p=Path(material_dir).expanduser().resolve()
 if not p.is_dir():raise ValueError('素材目录不存在')
 (ROOT/'本机配置.json').write_text(json.dumps({'material_dir':str(p)},ensure_ascii=False,indent=2))
 cfg=ROOT/'调度配置.json'
 if not cfg.exists():cfg.write_text(json.dumps({'draft_test_passed':False,'bindings_verified':False,'public_enabled':False,'native_tasks':{},'manual_ready':{},'timezone':'Asia/Taipei'},ensure_ascii=False,indent=2))
 Ledger().db.close()
 import bridge
 print('本机配置已保存。启动比特浏览器后，运行看板中的“发现全部频道”。')
 print('频道发现不会自动启用发布；运行绑定、权限检查和草稿验收仍需完成。')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--materials');a=p.parse_args()
 configure(a.materials or input('请输入本机素材目录：').strip().strip('"'))
