"""Per-computer paths; no credentials in the portable package."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
PATH=ROOT/'本机配置.json'
def read():
 return json.loads(PATH.read_text()) if PATH.exists() else {}
def source():
 value=read().get('material_dir')
 if not value:raise ValueError('请先运行首次配置，选择本机素材目录')
 p=Path(value).expanduser().resolve()
 if not p.is_dir():raise ValueError('本机素材目录不存在：'+str(p))
 return p

def save_source(value):
 if not isinstance(value,str) or not value.strip():raise ValueError('请选择素材文件夹或填写完整路径')
 p=Path(value.strip()).expanduser().resolve()
 if not p.is_dir():raise ValueError('素材文件夹不存在')
 config=read();config['material_dir']=str(p)
 tmp=PATH.with_suffix('.tmp');tmp.write_text(json.dumps(config,ensure_ascii=False,indent=2));tmp.replace(PATH)
 return str(p)

def choose_folder():
 import subprocess,sys
 if sys.platform=='darwin':
  result=subprocess.run(['osascript','-e','POSIX path of (choose folder with prompt "选择发布素材文件夹")'],capture_output=True,text=True,timeout=180)
  if result.returncode:
   if '-128' in result.stderr:return None
   raise ValueError('无法打开文件夹选择器，请填写文件夹完整路径')
  return result.stdout.strip()
 code='import tkinter as t;from tkinter import filedialog;r=t.Tk();r.withdraw();print(filedialog.askdirectory(title="选择发布素材文件夹"));r.destroy()'
 result=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,timeout=180)
 if result.returncode:raise ValueError('无法打开文件夹选择器，请填写文件夹完整路径')
 return result.stdout.strip() or None
