# 1.3.0 发布准备材料

此目录保存安装包的版本、摘要、大小、验证结论和发布步骤。DMG、应用 ZIP、离线源码 ZIP 尚未上传到 GitHub Release，不属于此 PR 的 Git 文件。SHA256SUMS.txt 对应这三个待上传的二进制附件。

Git 源码版本不携带运行时二进制基线；完整离线源码 ZIP 的摘要见 release-assets.json。源码 README 在 Git 中补充了二进制依赖获取说明，业务代码与已验证安装包一致。

update.json 中的下载地址是计划发布地址，附件实际上传前不可视为可用。在线更新 update.sig 必须由现有发布者密钥签署；当前缺少该签名，不可将未签名元数据当成已完成的自动更新发布。

发布步骤.md 按完整离线交付目录结构描述；Git 检出时可直接使用 source-v1.3.0/scripts 下的签名和验证脚本，并将 --manifest 指向本目录 update.json。请在上传完成并确认签名后再发布为 latest。
