"""Serve an isolated copy of the app without scheduler, auth or upload workers."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from http.server import ThreadingHTTPServer

with tempfile.TemporaryDirectory(prefix='ypp-120-ui-') as temp:
    root = Path(temp) / 'payload'
    shutil.copytree(Path(__file__).resolve().parents[1] / 'Resources/payload', root)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.path.insert(0, str(root))
    import dashboard
    (root / '调度配置.json').write_text(json.dumps({'execution_engine': 'local', 'local_public_enabled': True,'manual_ready':{'GM001':True}}))
    ledger = dashboard.Ledger()
    ledger.channel('UC-fixture', 'GM001', '界面验证频道', 'fixture-window', enabled=True, verified=True)
    dashboard.bit_windows.CACHE.update(items=[{'id':'fixture-window','name':'GM001','seq':1},{'id':'second-window','name':'GM002','seq':2}],updated='2026-10-15T10:00:00+08:00',error='')
    ledger.db.execute('INSERT INTO assets VALUES(?,?,?)', ('fixture', json.dumps({'video':'待检查视频.mp4','video_size':1400000000,'folder':'示例素材','description_source':'兜底配置','description':'测试兜底详情','raw_description':'','hashtags':'','missing_reasons':['封面匹配多个文件：封面A.jpg、封面B.jpg']},ensure_ascii=False), 0))
    ledger.db.close()
    server = ThreadingHTTPServer(('127.0.0.1', 0), dashboard.Handler)
    dashboard.PORT = server.server_port
    dashboard.ORIGIN = 'http://127.0.0.1:' + str(server.server_port)
    print(json.dumps({'url': dashboard.ORIGIN}), flush=True)
    server.serve_forever()
