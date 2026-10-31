# 信息层部署后最小补丁：来源链接补充误报冲突

用户于本信息监控聊天明确回复“允许转交并统一更新”。本补丁基于已统一部署的 53330c3869aa1ff4e39c7c41ec82243c6126491f；未修改当前运行源码，未重启任何服务。

观察结论分开记录：

- 待发现队列确实在推进。首笔 509 秒的新处理数为 0 不能作为持续阻塞结论；后续约 1416 秒时待发现降至 66、已处理 46，多个多维表来源已读取成功。当前是大量首次登记/读取造成积压，整体时效未验收；本次不修改调度、不扩展来源。
- 另发现 7 个 Docx 来源报 integrity_conflict。独立只读抽查 2 个：远端内容和版本与已存证据相同；仅旧 url=null、新 url 非空。把新观测中的 URL 恢复为旧 URL 后，完整 body_hash 与旧值精确一致。因此这是已核实的来源链接补充误报，不是对正文改变的猜测。

## 补丁范围

`AM-INFO-SYNC-20261030-01/R1/url-metadata-fix.patch`

只修改 am_info_sync/store.py，并新增 test_info_url_metadata.py。仅当 authoritative=True，且用旧 URL 计算的新观测完整哈希与旧哈希一致时，更新这一版本的 URL 和对应哈希；正文、payload、父对象、删除/完整度等仍按原规则校验。非权威事件改 URL、任何正文或 payload 改动，仍拒绝。

不创建新观察版本，不续期原文，不恢复已清理原文，不改权限/来源/业务状态，不新增发送或模型调用。

## 验证与应用

隔离候选完整 155 项检查通过，0 失败/错误；git apply --check 针对当前树通过。主工程源码未被替换。

- 基线 store.py SHA256：0ea67db023b15fb0b20f6886a2d96f761324d60df3c476c5ce25caaad20daeb1
- 候选 store.py SHA256：00ed39ebcf573bf60ccfc0e9c96dc09a30908953044ad2ee7a286c8b3d96a2b2
- 测试：evidence/url-metadata-fix-tests.json、url-metadata-fix-tests.log
- 真实读取比较：coordination/20261031/information-url-conflict-proof.json

请统一方在当前基线核对后应用补丁、做需要的联合检查，并仅在原业务和模型空闲时更新桥接服务。不重启 Qwen/Ollama，不改变配置。更新后仅需观察原报错来源回读是否恢复、完整性拒绝仍有效；历史失败记录保留，不能把部分图片/表格的解析缺口一起消掉。
