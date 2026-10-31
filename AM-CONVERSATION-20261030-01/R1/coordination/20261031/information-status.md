# 信息同步模块冻结检查点

2026.10.31。**可交统一更新；更新后运行观察待做。**

当前基线提交：`850906737e281642529e6ac723607559a826dcee`。本清单之后不再自行改动这些冻结源码，不单独覆盖共享配置，不重启桥接服务或 Qwen/Ollama。主工程其他聊天的修改保持。

## 文件与配置

完整机器清单：`information-frozen-manifest.json`。其中 owned_paths 是本模块源码/测试；shared_integration_paths 是已经合并的桥接接口，提交时保留同文件中的其他模块改动。当前加载版本与冻结文件的差异有 8 项，详见 manifest 的 differs_from_current_loaded。

生产配置已具有 am_information.enabled=true、discovery=true、ledger=true、owner_am_channel=true；本次冻结不要求更改生产配置。继续复用已登记起点和来源，不重建旧来源、不扩大私人会话范围。ledger_write=false；查询身份 600 秒。模型仍使用原 ModelCoordinator，同一进程只保留原长连接。

## 已完成检查

- 原包 121 项与宿主增量合计 **152 项通过，0 失败、0 错误**，详见 `AM-INFO-SYNC-20261030-01/R1/evidence/final-core-tests.json` 及日志。
- 已修复交付物发现饥饿：已知且未变更的记录不反复入队，未知记录按请求时间处理；每轮有界处理四项。
- 已修复文件缓存命中漏关联、文档/文件/表格/未支持类型统计混淆、数值 0 和布尔 False 行被当空行的问题；均有专门回归。
- 已增加云文档搜索自动登记、在线表格与多维表格分页/版本核对；多维表格独立记录不制造相互冲突。
- 真实只读证明：多维表格 20 条；在线表格 8 页 63 条非空记录，均进入证据和查询。此真实样本不覆盖所有表格形态；0/False 边界另由合成测试证明。
- 已有源读取→事实→AM 可信身份查询与同库查询一致，未为该查询探针外发消息。
- 真实 Qwen 样例：首次 120 秒超时被原协调器暂停，已通过服务端取消/释放/空闲证据恢复，未重启 Ollama；改用同一协调器 native_chat 后三例通过，预测/计划误标一例被拦截，修复后该例通过。当前 v2 又增加 observed_at 不换算相对日期提示；未重复做真实模型测试，业务语义全面验收仍待补。
- 原有版本跨夜持续运行，当前聚合状态见 runtime-checkpoint.json。不能把这一运行时段计作本次冻结增量已部署后的观察。

## 接口与边界

保留 `Legacy._LegacyProjects.read_project → am_conversation.capabilities.information` 的限量投影（limit=3、exclude_ledger=true），不注入 information.query 的完整对象。am_query 的 `_sync_observed_at` 与 information_source_check 保持。

新增源保持 owner-private。原固定 TH2 台账的部门/群开放口径不扩大。工作聊天按台账项目关联发现，普通机器人回答不作为新事实依据。消息事件仍走原唯一入口；用户身份来源以已绑定用户读取，不把机器人可见范围当成本人全量可见。

原文/引用按 24 小时规则清理，来源版本与结构化业务事实独立保存。备份原文和模型样例内容清空，备份保留不超过 24 小时。没有新增发送、审批批准、节点完成、交付物挂载或云端写回执行器。

## 权限与待验收

云文档搜索已实际成功，本次请求和 newly_granted 回执仅新增 search:docs:read，原授权未减少。完整授权聚合证据为 authorization-summary.json；返回令牌另含 7 项本次未申请的日历权限，来源未在本任务核定，不作为本模块授权，读取白名单不允许日历调用。

尚待：统一更新后核验加载指纹、连接和队列消退；本次队列修复真实生效；新发现表格持续读取；真人更正/撤回跨端闭环；完整业务语义、图像/OCR/未完整解析的表格与附件。台账有 18 条唯一项目/需求映射，另有三个 HD 分组行及两个未唯一映射项，不能声称全历史/全类型已覆盖。当前约 116 个发现项待处理的状态属于旧运行版本，不代表修复后结果。

本轮没有在执行新的模型验收或真实发送测试。可能仍有原服务的正常后台读取/用户交互；统一更新时以当时模型锁和业务队列为准。

## 回退依据

冻结源码副本：`AM-INFO-SYNC-20261030-01/R1/frozen-source/`。开工前 bridge.py/am_service.py/health.py 已在私有 validation/am-info-sync-r1/before-source 保存；不能用它们整文件覆盖此后并行的对话/文稿修改。协调方宜在统一更新前保留当前已加载文件副本。回退只恢复本轮信息层代码/开关，不还原旧业务数据库、不清除未知发送或模型状态；回退到不支持新云表格类型的版本时，暂停相应新类型来源，保留事实库和证据。

## 冻结指纹

| 文件 | SHA256 |
| --- | --- |
| `local-qwen3.8/feishu-bridge/am_info_sync/__init__.py` | `b09cf02f2b3a069b4b27c7af55b6af09b9102db44697f498924237b8aa019cad` |
| `local-qwen3.8/feishu-bridge/am_info_sync/__main__.py` | `935a1c1166b0c1ea35a82256345000bf2c73ded718d77773bc27a71ecce28f7d` |
| `local-qwen3.8/feishu-bridge/am_info_sync/adapters/__init__.py` | `960eccd62661ae509bef23498c9c254f440aa1a1402df23b2f51a21f55af343f` |
| `local-qwen3.8/feishu-bridge/am_info_sync/adapters/docx.py` | `c7284ee50ce8b0d5482d031d76eaab9c30a529e8ee1bbf7e345a8f2d7fc358bf` |
| `local-qwen3.8/feishu-bridge/am_info_sync/adapters/http.py` | `19bc43a114dd8abf22e65eea00651e6d2fa3925da1d4c481d0c3da1d0ffef3d7` |
| `local-qwen3.8/feishu-bridge/am_info_sync/adapters/messages.py` | `938420f77546f2eb5c5292062f8ad1462a8167914755df57427ec6bfdd11db86` |
| `local-qwen3.8/feishu-bridge/am_info_sync/adapters/snapshot.py` | `0dff090dcf30a70649d798429ed0ea10647eed4e1d1797019d20cb18c79d236b` |
| `local-qwen3.8/feishu-bridge/am_info_sync/catalog.py` | `4665f9ab4f16654f3b146917aec5467e137fc80e3b0044a9eb371582cd043bbb` |
| `local-qwen3.8/feishu-bridge/am_info_sync/cli.py` | `34231861d838b04bb25d4f3e4333cf5c5e10e0d0cb21882d146ae948ad18a17d` |
| `local-qwen3.8/feishu-bridge/am_info_sync/demo.py` | `a99a34e4632dfb8eee88f9b2e0b270622caf758087b3b130b4e99cb71e30ec42` |
| `local-qwen3.8/feishu-bridge/am_info_sync/extraction.py` | `c3939be7e8b4294a6f873d3c3c3d34a57b1f5308921735d54bd3a11a0f8c55a6` |
| `local-qwen3.8/feishu-bridge/am_info_sync/facts.py` | `060c86befec581bcca56ff7f24912212410369ea5be45282a7e4c87638892f0f` |
| `local-qwen3.8/feishu-bridge/am_info_sync/ingest.py` | `beb3de6adc48c7a631d4a61eb2fd1c387a4a64933ed3085147f4d2bcabb6d64a` |
| `local-qwen3.8/feishu-bridge/am_info_sync/models.py` | `2fcf389a5156f5ae3ab4c60884f5986d0674663c4dc8b50ac0815b3e9baac6d2` |
| `local-qwen3.8/feishu-bridge/am_info_sync/policy.py` | `f09d07222c51f01173f674706068fb81c0afb789e89fadc5735ed4f4bbd28f88` |
| `local-qwen3.8/feishu-bridge/am_info_sync/review.py` | `38c93ed59d9ce3e42ba0da7baf5f175c6c8bd2f528d3d4e3ddac99dac824d0be` |
| `local-qwen3.8/feishu-bridge/am_info_sync/runtime.py` | `1cc3c24064ce21856f72d20890c6967b35c3a0d6d678aa5933b7069227fb8aa0` |
| `local-qwen3.8/feishu-bridge/am_info_sync/store.py` | `0ea67db023b15fb0b20f6886a2d96f761324d60df3c476c5ce25caaad20daeb1` |
| `local-qwen3.8/feishu-bridge/am_info_sync/sync.py` | `79e95f0f0c4b8495948ccc80f55f23dcec1b70fb99a2b9de153f4676ecacac8e` |
| `local-qwen3.8/feishu-bridge/am_information.py` | `01cfb28685683532d6b426355679a3644e354d37d9ba6ff36319b8d5bbebb802` |
| `local-qwen3.8/feishu-bridge/am_query.py` | `1b7267b39eb12dadf027ca8ad1b8d32c928b82197cb4770aef0aae7cb070b236` |
| `local-qwen3.8/feishu-bridge/am_service.py` | `a6433b6422227444b03bfdf0e4d2cba0a6a0a2ac60e39258e17ae31ee0172fe0` |
| `local-qwen3.8/feishu-bridge/bridge.py` | `d798c8c92a28675c72383f49ad979ac4eea59413d9b0c0285539da0224f1a080` |
| `local-qwen3.8/feishu-bridge/health.py` | `8582188eada0e06361063947b8484332999118b7d5f6a9daabb375c0ec7ebb0b` |
| `local-qwen3.8/feishu-bridge/info_cloud.py` | `85d730151982612ff96d19e4a9f61f02888f46b3dd2c23a5b6d35b0d8099844b` |
| `local-qwen3.8/feishu-bridge/info_extraction.py` | `eb60108779a1f971503b10aa96989a2b516a52ec3d3ae10d7707ffb4e5cf9bd2` |
| `local-qwen3.8/feishu-bridge/info_readers.py` | `c586f83db62ee31e14f50ec08f037833286cc2885dd1e3860f0f5168181d9dc0` |
| `local-qwen3.8/feishu-bridge/info_sources.py` | `cd6cbfe979fd2e615c5f6758d91e2f4de9ef421e550d9b704250a0096767a058` |
| `local-qwen3.8/feishu-bridge/test_am_information.py` | `2d9a784f8eaa4e9b27ac41c964a540a2a06e084a9833cf719c4bdb40a8c1ff31` |
| `local-qwen3.8/feishu-bridge/test_info_cloud.py` | `b69e419e472b022f3349480116ec1f70b57d346b90b437f1d5c5aaf166aab09a` |
| `local-qwen3.8/feishu-bridge/test_info_sources.py` | `a8b73233c8ea1608b817d290a65e4a1bdbdd37b41a0e0080bb105a4ec5ee1b18` |
