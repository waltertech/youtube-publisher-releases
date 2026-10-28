"""Shared concurrency cap; task state files are isolated by immutable task ID."""
import json,os,re
from pathlib import Path
ROOT=Path(__file__).parent
PATH=ROOT/'并行设置.json'
def validate(n):
 if type(n) is not int or not 1<=n<=5:raise ValueError('并行数量必须是 1–5 的整数')
 return n
def read():return validate(json.loads(PATH.read_text()).get('concurrency',1)) if PATH.exists() else 1
def save(n):
 n=validate(n);p=PATH.with_suffix('.tmp');p.write_text(json.dumps({'concurrency':n}));p.replace(PATH);return n
def task_path(task_id,kind='input'):
 if not re.fullmatch(r'[a-f0-9]{32}',task_id):raise ValueError('无效任务ID')
 folder=ROOT/'.task-state';folder.mkdir(mode=0o700,exist_ok=True)
 return folder/(task_id+'.'+kind+'.json')
def write(path,data):
 tmp=path.with_suffix('.tmp');fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
 with os.fdopen(fd,'w') as f:json.dump(data,f,ensure_ascii=False)
 tmp.replace(path)
