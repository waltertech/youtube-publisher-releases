> 当前修订版本为 **1.3.1**，保留原源码目录名以保持 PR 路径稳定。修复本机调试连接误走系统代理及频道配置结果误报；发布说明见 `../releases/v1.3.1/RELEASE-NOTES.md`。

# YouTube 发布工作台 1.3.0

基于 waltertech/youtube-publisher-releases 的 1.1.10 已发布应用提取的业务源码升级。支持 macOS 12+，包含 arm64 与 x86_64 运行依赖。Intel 尚未实机验证。

启动时会核对后台版本；旧后台空闲时备份并切换，有上传或操作时提示等待，不中断现有任务。

## 本次变更

点击首页“素材与文案设置”打开弹窗，配置文案/封面文件名关键词和兜底详情内容。文案使用UTF-8 TXT，封面支持JPG/JPEG/PNG。

详情优先级：原详情非空时完整保留；否则使用Hashtags全部内容；两者都空时才使用兜底文字。兜底仍为空则标记不完整。Studio Tags独立填写，空值跳过。

设置保存后，可点击“刷新未分配素材文案”轻量应用到已扫描且视频未变更的未分配素材，不重新哈希大视频。已创建的任务保留原文案；新增或变更视频需要完整扫描。设置不会修改源TXT文件。

窗口选择区独立列出已选数量和具体窗口/频道。在“自动配置全部频道”旁点击“自动配置选择频道”，仅操作所选窗口的频道发现、权限核验和运行绑定，不触碰其他窗口。无选择时按钮禁用。

窗口列表下方统计当前已获取并完成核验、启用和运行绑定的可发布频道数，与勾选数量独立；每日任务额度和素材是否充足另行检查。

## 文案样例

见 `examples/发布文案示例.txt`。区段名称独立成行。详情中现有 hashtag 原样保留，不会自动补 #、修正拼写或重新生成正文。

## 开发与验证

开发测试使用 Python 3.12+，先安装 `Resources/payload/requirements.txt` 中的依赖（含 websockets）。界面测试另需 Node.js、playwright 和 Google Chrome。

业务代码在 `Resources/payload`，网页在 `Resources/payload/dashboard/index.html`。应用版本在 `Info.plist`。

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
node tests/test_workflow.cjs
# 界面测试需要 npm 安装 playwright，并安装 Google Chrome；不会触发真实上传。
node tests/test_ui.cjs
```

`tests/test_ui.cjs` 在临时目录运行隔离服务，测试关键词保存、持久化、非法输入拦截和界面展示。`YPP_VERIFICATION_DIR` 可指定截图输出目录。

## 构建安装包

本包包含 Python/网页/工作流等业务源码，以及构建、验证、签名脚本。原作者的 Swift 启动器源码未提供；使用 1.1.10 的已编译双架构启动器和第三方运行时基线，修改程序资源后重新进行 ad-hoc 签名。此包不是从 Swift 源码完整重编译的工程。

完整离线交付源码包配套 `dependencies/YouTubePublisher-runtime-baseline-1.1.10.zip`，保留原版已签名应用，可据此重复构建。Git 仓库不提交该二进制 ZIP；从 Git 检出后可使用本机原版 1.1.10 应用作为 `--baseline-app`，或将原作者提供的运行时基线 Release 附件放入 `dependencies/` 后使用 `--baseline-zip`。它包含可执行文件和第三方库，不包含用户素材、账号配置或台账。原版启动器和第三方依赖的源码、许可证权利归各自作者；其中依赖来源见 `Resources/dependency-sources.json` 和运行时包内许可证。未据此为整个项目新增开源许可证。

```sh
python3 scripts/build_macos.py \
  --baseline-zip dependencies/YouTubePublisher-runtime-baseline-1.1.10.zip \
  --output ./dist
python3 scripts/check_release.py ./dist
```

也可以用 `--baseline-app /Applications/YouTube发布工作台.app` 指向原版 1.1.10 应用。构建过程不会替换当前安装或修改实际用户台账。DMG/ZIP 支持手动安装；无 Apple Developer ID 签名和公证。

## GitHub 在线更新签名

旧客户端内置原作者 Ed25519 公钥。`update.json` 必须由配对私钥生成 `update.sig`；SHA-256 校验和不能替代此签名。未提供私钥，因此交付时签名状态是 pending，不能称为已完成自动更新发布。

安装开发依赖 `cryptography` 后，由持有原私钥的发布者执行：

```sh
python3 scripts/sign_update.py sign --manifest /path/to/GitHub发布包/update.json --key /secure/path/to/original-ed25519-key
python3 scripts/sign_update.py verify --manifest /path/to/GitHub发布包/update.json
```

支持未加密 PEM、32 字节原始 seed、base64 编码的 32 字节 seed。脚本检查私钥与既有公钥一致，拒绝错误密钥。不将私钥放入源码、发布文件夹或 GitHub。

完成签名后运行 `python3 scripts/write_checksums.py /path/to/GitHub发布包` 重新生成 SHA256SUMS.txt，并运行 `scripts/check_release.py`。GitHub 发布步骤见交付目录的 `GitHub发布包/发布步骤.md`。
