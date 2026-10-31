# 文档模块冻结状态 — 2026.10.31

结论：**文档 R1 已冻结，无需再合回源码；本次不改代码、不重复测试，由对话接入聊天统一最终更新原服务。**

本次对主工程中的 32 个文档模块文件逐项计算 SHA-256，与已发布审核包 `verification/VALIDATION.json.runtime_source_files` 比对，32/32 一致，无缺失文件、无内容差异。当前 Git 状态中的 5 个已跟踪修改与 27 个新增未跟踪文件已经实际落在主工作树；“尚未统一提交”不等于“尚未合回”。最终提交／快照应保留这些文件，不能以旧分支整文件覆盖当前对话或信息模块。

## 核对依据与范围

- 主工程当前 HEAD：`d0bb75cfe372190b166b684afffd974a6f2f60d5`。
- 文档源码冻结提交：`efe3d967b7936584c31bd6cc09ad84ad3d70edb8`，独立分支 `codex/am-doc-standards-r1`。
- [文档 R1 固定交接](https://github.com/Catcherog/project-workbench-review/blob/096ff82575f645590b33a0d2a84bb8705f938751/AM-DOC-STANDARDS-20261030-01/R1/00_%E5%BD%93%E5%89%8D%E4%BA%A4%E6%8E%A5.md)。上一轮已从该提交回读 79 份文件，字节和模式全部一致；本次未重复远端回读。
- [对话 R1 固定交接](https://github.com/Catcherog/project-workbench-review/blob/7445333757fd39b674caa7cca8237ee9ecc46f89/AM-CONVERSATION-20261030-01/R1/00_%E5%BD%93%E5%89%8D%E4%BA%A4%E6%8E%A5.md)，由本次协调消息提供。本次核对接口以本机实际源码为准。
- 当前自然语言适配文件：`am-conversation-r1/src/am_conversation/documents.py`，SHA-256 `21d6621f15bd188e7cd21acf324aafd13d94f5e1276af7dd4cfd78fd9375b640`。
- 本次动作仅限本机文件／配置元数据读取、静态接口检查及本文件写入；未调用模型，未访问或生成云文档，未运行检查套件，未重启任何服务，未发起真实挂载。

## 必要配置

保留原 `Config.root` 下私有 `config/document-standards.json`，不要用公开 example 覆盖它。本次读取其状态为 `enabled=true`、`ledger_write=false`、`catalog_identity=owner`；文件权限 `0600` 且归当前服务用户所有。配置 SHA-256：`2b2d8c7bee4674c27df1eb5dde4e50848ef440a9011e927d77c60aba3b6b64e4`。

已有 CLI 路径存在，当前可执行文件与配置指纹一致；现有 CLI profile、应用／本人身份绑定、真实台账与目录入口、4 份必读资料、本人输出目录及三类模板映射均保留。未在此复制凭据、人员 ID、真实资源标识或内部模板原件。本次没有重新验证登录令牌或云端权限。

原 `document-business.json` 中目标别名仍仅有“测试报告”。章程／变更申请／结项报告的真实挂载继续等待准确项目、节点和交付物绑定；不能扩大原目标的用途或略过项目／文种检查。

打包声明已经包含 `src/fs_agent` 与 `src/am_doc_engine`。继续使用原模型 Provider／ModelCoordinator、原服务运行目录和唯一消费者，不另装模型或新建消费入口。主桥接配置本次核对为 `am_self.ledger_write=false`、`am_query.identity_cache_seconds=600`。600 秒是查询身份配置，不替代文档采用／发布等动作的原实时核权。

## 接口兼容性（静态核对）

- 自然语言适配复用 `LogicService.get/add_source/queue/adopt/select_target/mount/reconcile_draft` 与 `standards.authorize/context/native_action`；调用签名及使用的 SQLite 字段／表与当前冻结模块一致。
- `template` 新稿使用当前 `logic_drafts`、`amdoc_context` 字段结构；派生内部任务链接实际入站事件，并进入原 `logic.queue`。没有增加第二个模型入口或消费者。
- 自然语言独立新稿直接建立新的 draft ID，保留旧稿；这与原 `/doc logic` 创建语义分开，未要求文档模块回退或覆盖这项后续行为。
- 采用仍绑定准确 revision 和 content hash；自然语言发布在原动作预览基础上再次核对版本、`accepted_hash` 及目标，保存和挂载分别调用原接口。原生修订保存新版本，未知结果先对账。
- **调用顺序约束**：`select_target` 会增加草稿 revision 并清空采用状态；`native_action` 按当前 revision 查 `amdoc_results`。选择／更换目标后，若还要保存云文档，需先形成与当前 revision 对应的新结果，再采用／发布；不得拿旧结果或旧 hash 绕过 `DOCUMENT_STANDARD_RESULT_REQUIRED`。这一联合序列仍需协调方纳入验收，静态匹配不代表所有交互顺序已通过。
- 本次未发现需要修改接口签名或数据库字段才能接通的源码缺口；没有对新自然语言入口作端到端通过声明。

## 已完成验证（沿用 2026.10.30 记录，本次未复跑）

- 输入 ZIP 及 51 项文件清单核对一致；原包 3 个合成示例已运行，119 项核心检查通过。
- 原宿主相关检查 130 项通过，含本轮新增 36 项；两组共 249 项。脱敏重建另复现 155 项，是上述检查的子集，不重复累计。
- 真实目录及三类模板／标准全文读取，真实项目草稿、原生副本保存及独立回读已执行。早期默认链接分享问题已纠正；后续流程先核验副本关闭链接分享和外部访问，再填写项目资料。
- 真实字段显示修订保存为新副本，旧文档保留并独立核对内容哈希未变。
- 真实 Qwen＋合成资料完成风格提炼、2 个叙述字段生成及语义核对，3 次成功调用；不能当作公司范例或真人验收。
- 真实规则提炼未取得有效候选：先遇忙，后续调用超时进入 `STOP_UNKNOWN`。该失败及恢复均保留，不记为通过，也不因此替换原模型。

## 仍待验收／接续

1. 匹配的真实挂载目标及其实际回执；当前没有本轮真实挂载或专业批准结果。
2. 新自然语言文稿入口的真人连续操作、目标绑定后重生成／采用／保存的联合序列、第二位测试者与手机检查。
3. 真实规则提炼在既有预算内的效果，以及指定公司范例的风格采用和新项目对照。
4. 项目类型／级别和裁剪依据、真实测试／验收证据，以及当前带缺口草稿的业务内容充分性。
5. 复杂图片／嵌入对象、超长文可恢复分批、真实模板升级迁移，以及有据人工修改后的完整修订。
6. 不确定复制回执经对账定位后的后续处理仍由操作人决定，不自动续填或重复创建。
7. 文档模块尚未消费并行信息模块的共享事实接口；本次未新增该连接，也不把对话模块的信息查询能力当作文档取证已经接通。

## 后续恢复处理保留

按 2026.10.31 统一协调消息：`f0dd…` 已停止的失败请求目录残留曾再次触发启动暂停；协调方复核空闲槽位、后续成功调用及原恢复证据后，已归档到私有验证目录，没有重启共享模型，也没有重跑旧请求。此后续处理应保留，不能从旧文档快照把该目录或旧暂停标记恢复回去。

本次仅核对活动 `poc/tasks` 中已不存在该 `f0dd…` 目录，未重新检查服务端槽位或回放日志，也未移动／删除归档。具体归档位置及后续恢复证据以统一协调方的私有记录为准。

## 当前文件与哈希

下列路径相对主工程根目录；每项均与文档冻结审核包相同。Git 状态仅描述当前主工作树，统一提交由协调方安排。

| 文件 | 当前 SHA-256 | 主工作树状态 |
| --- | --- | --- |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/pyproject.toml` | `b6f0e109629d15dcb1ffe2dd2d5c23af3ba40cc13c17ed9cd2808ecdd9e191d7` | 已跟踪修改 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/fs_agent/logic_service.py` | `0d65b69471fbd72ff9632cd7b66227e3ec9d4bdfe9c24a52a6d0068790bc113f` | 已跟踪修改 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/fs_agent/meegle_port.py` | `bbf83d5222d74c7bf25001014bd3a0561a848fae33fb5eda41e7660656888afd` | 已跟踪修改 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/am_doc_engine/catalog.py` | `8df2b98f684767e1cb65f50ef3e5ea1fb9b82a30fa2bc11c5a9f9eeb9247fb29` | 新增未跟踪 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/am_doc_engine/compiler.py` | `3450bd223566712331a41634acf15d6bdcc5c48b720767635d21b1df2478122c` | 新增未跟踪 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/am_doc_engine/models.py` | `37790f971cb7563753b5971670efb5de0e8a77dbd6e09f187c8f9e2cc482a893` | 新增未跟踪 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/am_doc_engine/style.py` | `009d3ddaa1686b4fb8fb294ebbb4152470fa21bbf4ada0c50e27ba5593a65855` | 新增未跟踪 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/am_doc_engine/rendering.py` | `a60f7d2f9230911e05a21b69d2834cc83344d452e6d466577169e0d648a54632` | 新增未跟踪 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/am_doc_engine/content_checks.py` | `d8b019e32d89201e7a061475dbd4f53fdc6d22bddd988f9e61f896303a8acd0a` | 新增未跟踪 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/am_doc_engine/host_bridge.py` | `a6f8c07b5a0cc677f7afa53230fdf8411bd9bee07236bd28105704b097bc3d52` | 新增未跟踪 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/am_doc_engine/revalidation.py` | `0191cefaef7f286a2a463d05931cd791d93c5f13d2801271bc6a2f3bd92d3d6d` | 新增未跟踪 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/am_doc_engine/__init__.py` | `fbebee6954319b3b9a011f8e29486639760d535e4b9da33da120ad3ec4abe4c6` | 新增未跟踪 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/am_doc_engine/review.py` | `215b3eba9ae4c7905e1b95e40536e9fa2e12d811e4d9251ced41d64c99ffce01` | 新增未跟踪 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/am_doc_engine/sources.py` | `16a6ce8b51a6e27e38399d856d3d84ba758fbb5a0cc95cc11777bcf7c2cd617a` | 新增未跟踪 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/am_doc_engine/engine.py` | `5cb0df5b9d666d0aad14ccc76f29242b8aa2f8d0fee9c4969a95832119c672be` | 新增未跟踪 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/am_doc_engine/cli.py` | `0943b579a4fe7bcf37bf3465af86b8f9ffc7a3c884552e5f8ea2b54de5aff0d4` | 新增未跟踪 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/am_doc_engine/storage.py` | `cf433da4463fe0354212a860c50b8590419104a2e7ec18e36f5caff5b4895230` | 新增未跟踪 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/am_doc_engine/revision.py` | `39071f847a2873dedb8bc27fa3d5c774d7674e418d6dd192c9a5a6cb51da2646` | 新增未跟踪 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/am_doc_engine/evidence.py` | `c945cea05c67d94049b76135723a591baf2d23158a3ff5c1d8bc6ddebcfc5026` | 新增未跟踪 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/am_doc_engine/__main__.py` | `935a1c1166b0c1ea35a82256345000bf2c73ded718d77773bc27a71ecce28f7d` | 新增未跟踪 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/am_doc_engine/adapters.py` | `c90f90967d2760a2f56e23d7027b06097e67dedbfc0a7e2ba193cd34f3a8f083` | 新增未跟踪 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/am_doc_engine/validation.py` | `86b242d2855431b352064776cfcbb67d1cef2de9e44afbb0b9ae31b44324d6d1` | 新增未跟踪 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/fs_agent/document_sources.py` | `3eaa0860b2cc7e9d785e72a696115b797cbe8adc8210446c91031ba9337a6ae6` | 新增未跟踪 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/fs_agent/document_mapping.py` | `ceb324ef25e61fd40010206a0b8af996b05491e30803304626846b6e7848c6b4` | 新增未跟踪 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/fs_agent/document_native.py` | `12a80c8c06c73e5e7df5094949301711d0507c13f8fdc270ab6949712a525cca` | 新增未跟踪 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/fs_agent/document_standards.py` | `fb2b7c47ad793bff4bcb900b992bb40c6fc4a90267787c7006cf88f2210f5bb5` | 新增未跟踪 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/tests/test_document_standards.py` | `46b88dc1cc42e9bc7c29824b41cf975e484a0d94b98e11a2459333c8223f622f` | 新增未跟踪 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/scripts/verify_document_standards_live.py` | `36bd5aaa3d8be292545aac9bfb0ed267b7f0050a57ecef349eaa722708917483` | 新增未跟踪 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/scripts/verify_document_model_live.py` | `345bc4c3aca5ccef757fffa318a68ff155528a41d7d3873872edd96f53ab664d` | 新增未跟踪 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/config/document-standards.example.json` | `97515e4c1b18060010185a57afc3923fd6f5fc8446ebbc57535e4f8c3ac0dd87` | 新增未跟踪 |
| `FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/fs_agent/gateway.py` | `d09f4337468bfa8fafb8bf4e1d8adbd52a24954b7eca3dc012d916830a18b8a0` | 已跟踪修改 |
| `local-qwen3.8/feishu-bridge/am_documents.py` | `07b86677b215e46f5adbc951bec28a616c1c0c1e34448433e8045c7f5df1fb97` | 已跟踪修改 |
