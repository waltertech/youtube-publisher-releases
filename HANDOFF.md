# YouTube 发布工作台：开发交接

核对日期：2026-10-28（Asia/Taipei）。

## 仓库与代码位置

- 仓库：https://github.com/waltertech/youtube-publisher-releases
- 当前开发分支：`codex/v1.3.0-fallback-window-settings`
- 当前业务源码目录：`source-v1.3.0/`。目录名保留历史命名，程序版本已经是 **1.3.2**。
- 最新已发布版本：`v1.3.2`，发布源码提交 `814428b`。
- PR：https://github.com/waltertech/youtube-publisher-releases/pull/1
- 默认分支 `main` 仍是早期发布仓库状态。接手开发请显式检出上述开发分支，不要把 main 当成最新业务源码。

```sh
git clone https://github.com/waltertech/youtube-publisher-releases.git
cd youtube-publisher-releases
git switch codex/v1.3.0-fallback-window-settings
cd source-v1.3.0
```

## 主要模块

`Resources/payload/`：

- `dashboard.py`、`dashboard/index.html`：本地管理 API、任务列表、预览和进度界面。
- `publisher.py`：SQLite 台账、素材去重、计划、事务领取、状态迁移。
- `manual_queue.py`、`scheduler.py`、`parallel_settings.py`：手动队列、定时调度、并行名额和任务独立状态文件。
- `bit_windows.py`、`installation.py`、`onboard_windows.py`、`channel_probe.py`、`configure_bindings.py`：窗口读取、逐窗口发现频道、权限核验和执行绑定。
- `local_transport.py`：本地回环 HTTP 与 WebSocket 绕过系统代理；外部请求保持原网络策略。
- `bit_runner.py`、`file_adapter.py`、`通用流程-无凭据.automa.json`：本机浏览器执行、文件提交与页面步骤。
- `task_progress.py`：逐任务并行采集上传进度，拒绝含混百分比。
- `refresh_task.py`、`retry_task.py`、`publish_draft.py`：按已有视频 ID 核查、人工确认后的重新上传、已有草稿发布。
- `feishu_auth.py`、`feishu_sync.py`：用户独立授权和台账同步。

`Resources/bootstrap.py`、`runtime_upgrade.py`、`update_install.py`：启动、运行时升级和安装恢复。

## 最近完成

### 1.3.1

- 修复 macOS 系统 SOCKS 代理导致本机 CDP WebSocket 报 `connecting through a SOCKS proxy requires python-socks`。
- 回环连接明确直连，不需要关闭用户 VPN，也不改变比特窗口访问 YouTube 的代理。
- 逐窗口完成发现、权限核验和启用；失败继续其他窗口，全部失败明确报错。

### 1.3.2

- 顶部展示全部执行中、待执行任务。
- 任务进度独立连接、并行采集；30 秒过期不再显示旧百分比。
- 区分上传百分比与视频处理百分比，含混进度不猜测。
- 预览显示任务草稿/正式发布类型，待执行任务读取有效队列的发布类型。
- 验证通过：45 项 Python 测试、5 项工作流检查和浏览器界面测试。没有启动新的真实 YouTube 上传验证本次修复。

## 当前待完成：上传完成后不等待画质转换

用户最新要求：

1. 草稿模式：上传完成，选择私享并确认保存后释放任务，让队列继续；不等待 SD/HD 转码。
2. 正式发布模式：上传完成，平台允许时选择公开并提交；不等待 SD/HD 转码。

**这项仅完成代码定位，尚未修改、测试或发布。不能宣称 1.3.2 已实现。**

已定位阻塞：

- 通用流程节点 12 依赖 `Checks complete` 文本，并固定点击“下一步”。
- 节点 16 草稿分支仅保留页面，没有主动选择 PRIVATE 并确认保存。
- `file_adapter.validate_draft_evidence()` 强制要求检查完成文本；同时被草稿确认和正式发布准备复用，应拆分证据要求。
- `confirm_draft()` 依赖原上传对话框；保存关闭后应能核对准确视频 ID、频道和已保存私享状态。
- `confirm_public()` 要求 `Video published` 成功文本。若平台仅接受公开提交但仍显示“正在处理视频”，需要把“提交成功”和“实际公开成功”分开，不应虚报已发布，也不应持续占用上传槽位。
- `publish_draft.py` 也复用旧检查条件，需要同步覆盖已有草稿转公开路径。

实现注意：仅上传字节完成不是保存成功。保留视频 ID、频道、保存结果及可见性的核对；平台阻止提交或返回版权/验证错误时记录具体原因。若新增“已提交、平台处理中”状态，必须同时检查队列释放、每日发布限制、去重占用、状态刷新、重试、飞书同步和界面，防止重复上传或同频道超额。

## 本地运行与测试

实际用户数据默认在 `~/Library/Application Support/YouTube发布工作台`。本机管理端口 18741，桥接 18740，比特 Local API 54345；配置/核验锁端口 18742、18744。

不要为了测试覆盖用户数据、终止现有上传或对所有账号执行初始化。界面测试使用隔离副本，不启动真实上传或调度。

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
node tests/test_workflow.cjs
node tests/test_ui.cjs
```

Python 依赖见 `Resources/payload/requirements.txt`。UI 测试需要 Node 的 `playwright` 和本机 Chrome，可通过 `NODE_PATH`、`CHROME`、`PYTHON` 指定环境。

部分旧测试实际绑定配置锁端口。工作台正在配置时可能产生端口占用失败，应隔离/mock 锁依赖或在空闲测试环境运行，不应强制停止用户任务。代理测试包含真实本地 HTTP/WebSocket 服务，不能全局 mock socket 后声称这些连接已测。

## 构建和在线发布

```sh
python3 scripts/build_macos.py --baseline-zip /path/to/YouTubePublisher-Mac-1.1.10.zip --output ./dist/VERSION
```

基线 ZIP 从仓库 v1.1.10 Release 获取。构建复用基线已编译启动器和 arm64/x86_64 运行时；该分支尚无原始 Swift 启动器源码。不要用缺少运行时的源码目录直接分发。

版本更新涉及 Info.plist、dashboard 返回版本、构建/校验脚本、测试夹具和页面版本标识；检查所有版本字符串。

发布文件：DMG、ZIP、`update.json`、`update.sig`、`SHA256SUMS.txt`、`BUILD-INFO.json`。

1. 完成回归测试、隔离初始化、安装包完整性检查。
2. 使用原发布者 Ed25519 私钥签署原始 `update.json` 字节，核对客户端内置公钥。私钥只由发布者保管，不在仓库、安装包或交接文档内提供。
3. 签名完成后刷新校验和，核对 BUILD-INFO 的真实验证状态。
4. 源码提交并推送；Release 指向完整提交 SHA。
5. 先创建 draft Release 并上传所有资产，确认全部为 uploaded 后发布并设 latest。
6. 从真实 `/releases/latest/download/update.json` 与 `update.sig` 下载并验证版本、内容和签名，再宣称在线升级已生效。

`sign_update.py` 需要 cryptography，也可使用发布者已有原生签名工具；不要为了签名换一套密钥，旧客户端将无法验证。

安装包采用 ad-hoc 签名，未 Apple 公证。Apple Silicon 已本机构建验证；包含 Intel 运行时，但 Intel 未实机验证。

## 数据与凭据边界

SQLite 是权威任务台账，飞书是管理和同步视图。相同视频 SHA-256 保持全局唯一分配，素材改名不能绕过去重。结果不明保持占用，先核查原视频；“重试”代表用户确认失败后重新上传，不可自动把未知状态当失败。

频道 ID 是核对身份的依据；切换失败停止该窗口任务。并行窗口互不阻塞，同一窗口频道顺序执行。

仓库不应包含 OAuth token、飞书 Secret、更新签名私钥、用户数据库、素材、浏览器配置或账号日志。跨电脑部署使用各自授权；迁移发布台账时须保持去重记录。
