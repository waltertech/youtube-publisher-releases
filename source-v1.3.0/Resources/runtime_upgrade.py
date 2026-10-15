"""Reuse the matching dashboard or safely retire an idle older local service."""
from contextlib import ExitStack
from datetime import datetime
import json
from pathlib import Path
import socket
import urllib.error
import urllib.request
import uuid
import update_install

ACTIVE = {'上传中', '填写中', '检查中', '发布中'}


def ensure_current_service(root, port, url, version):
    try:
        with urllib.request.urlopen(url + '/health', timeout=2) as response:
            health = json.load(response)
    except (OSError, ValueError):
        return False
    if health.get('service') != 'ypp-dashboard':
        raise ValueError('工作台端口被其他程序占用，请先关闭占用程序')
    if Path(health.get('data_dir', '')).resolve() != root.resolve():
        raise ValueError('正在运行另一数据目录的工作台，请先关闭该工作台')
    if health.get('version') == version:
        return True
    lock = root / '.update-lock'
    try:
        lock.mkdir()
    except FileExistsError:
        raise ValueError('已有更新正在运行，请等待完成')
    try:
        with ExitStack() as stack:
            # These are the existing dispatch/probe guards. Block new starts while checking.
            for guard_port in (18742, 18744):
                guard = stack.enter_context(socket.socket())
                try:
                    guard.bind(('127.0.0.1', guard_port))
                except OSError:
                    raise ValueError('旧后台仍在启动任务或核查频道，请完成后重新打开新版')
            with urllib.request.urlopen(url + '/api/status', timeout=10) as response:
                status = json.load(response)
            if status.get('job', {}).get('running') or any(t.get('state') in ACTIVE for t in status.get('tasks', [])):
                raise ValueError('旧后台仍有上传或操作，已保留原任务；请完成后重新打开新版')
            pids = update_install.services(root)
            if not pids:
                raise ValueError('无法确认旧后台进程身份，请退出工作台并重启 Mac 后再打开新版')
            backup = root / '更新备份' / ('启动升级-' + datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6])
            update_install.backup(root, backup)
            update_install.terminate(pids)
            return False
    finally:
        lock.rmdir()
