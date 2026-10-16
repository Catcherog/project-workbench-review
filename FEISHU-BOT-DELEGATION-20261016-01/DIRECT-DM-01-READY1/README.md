# DIRECT-DM-01-READY1

从00_当前交接.md进入。当前完整工程结果：R1 34/34、DM 108/108、FIX3 84/84、事件桥5/5。FIX1历史61/62保留。15文件安装候选尚未安装，真实绑定仍有缺口。

复现：Node>=22.13，parse5 8.0.1；`node tools/build-manifest.mjs`，`python3 tools/run-verification.py`。本机使用已存在依赖，不更新正式依赖。不要默认启动完整host。全部服务测试在隔离目录/端口、显式testMode:true和legacy:null下运行。

审核包没有真实ID、凭据、有效批准、生产密钥或平台正文；真实信息留在private，不上传。
