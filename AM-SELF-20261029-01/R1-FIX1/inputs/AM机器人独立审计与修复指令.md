# AM机器人独立审计与修复指令

日期：2026-10-29（Asia/Shanghai）  
审计任务：AM-SELF-20261029-01 / R1  
结论：**需要定向修复。独立源码与隔离审计已完成；用户验收仍待执行。**  
下一轮：AM-SELF-20261029-01 / R1-FIX1  
补充需求版本：v1.1-exec（补充v1.0-exec；未冲突的原要求继续有效）

## 一、结论与适用范围

A→D已有实质实现，原回传区分了源码、隔离验证、真实模型/平台、安装启用和用户验收。本轮确认了正式写回关闭、精确批准、部分未知结果保护等边界，同时复现八项缺陷。因此不能将R1记为“GPT审计通过”，后续也不只是补真人验收。

这些问题可以在原AM架构内修复，不需要重做四批、接入工作台或用户重选技术方案。建议先处理未知发送保护、连续反馈，再处理查询/简报和D链路；独立部分可以并行。

本轮未修改原工程、更新Studio服务、发送飞书消息、创建真实计划/订阅、写正式台账或挂载真实交付物。原服务已安装、唯一消费者等判断来自固定回传，不能表述成本轮已直接登录Studio实时检查。

### 版本和依据

- 源码SHA：`6528b9a435b5f4a2406080908a6ddaa823ee61b1`。
- 审核SHA：`496d403a69d814818cbced5e427f72ddf8aef5b2`。
- [固定交接入口][handoff]、[有效需求][requirements]、[文件清单][manifest]、[最终差异][diff]、[执行端验证记录][validation]。

### 本轮独立验证

| 项目 | 实际结果 | 限制 |
| --- | --- | --- |
| 审核包 | 106个文件按Git blob SHA独立核对；其中104个另与清单SHA-256一致 | 未独立核对全部文件模式；私有原工程与脱敏副本差异按清单记录 |
| 原测试集 | 370 passed、1 skipped、1 deselected，0 failed | 不能写成GPT独立372项全通过 |
| 跳过项 | 服务账户检查要求非root用户，本环境为root | 不表示此项已在本环境通过 |
| 排除项 | macOS sandbox-exec专属检查，本环境为Linux | 不以Linux替代Mac沙箱验收 |
| 新反例 | 八项缺陷均以实际模块、临时SQLite、合成消息和端口复现；主审已复跑 | 不表示生产已发生事故 |
| Qwen/平台/Studio | 阅读固定证据，未重新调用真实环境 | 执行端实测不等于本轮云端实测 |

依赖按审核包requirements.lock.txt对齐，pytest 8.4.2；本环境Python 3.12.14，原运行记录为3.12.13。八项问题属于明确逻辑分支，不需要真实外发才能证实。

**附包反例退出0表示“旧版缺陷复现成功”，不是“修复通过”。** 修复方应将错误结果反转为正确行为断言，形成回归测试。

## 二、已确认有效的实现

1. **正式台账写回在执行层关闭。** LedgerChanges.execute首先检查enabled，关闭时返回LEDGER_WRITE_NOT_ENABLED；卡片批准不能打开开关，默认值也为false。[源码][ledger]
2. **批准字段子集被保存并执行。** 非owner不能批准，实际端口限制既定表/工作表的待办、项目进展单元格，保留当前原值、受控窗口、富文本/公式保护。
3. **事实表达采用保守回退。** 完整字段原文与对象、来源绑定；无法可靠验证自由改写时回退已确定项目原文；准确编号固定字段有无模型查询路径。[源码][groupai]
4. **原提醒的预览、版本与期限保护有实现。** 同Store原子建立预览/outbox，旧revision失效，单实例unknown不直接重发。F01是跨已有待发实例的遗漏。
5. **模型执行已统一协调。** 普通私聊、群、提醒、文档共享协调器，STOP_UNKNOWN暂停后续推理，确定查询等路径不必调用模型。[源码][model]
6. **附件解析有资源边界。** 独立进程限制大小、解压、页数、CPU/时间/RSS，保留扫描/加密/损坏/读取不完整性质；预检不自动改变专业审核或节点状态。

## 三、八项确定缺陷

### F01｜P1：同事项已有待发实例绕过未知结果保护

**影响：** 第一条通知可能已发送但回执丢失，第二条已排队通知仍以另一请求键发送，存在重复催办风险。

**复现：** 同事项、同目标、同正文，两个已批准计划同刻到期。scan创建两个ready；第一次dispatch模拟SendUnknown，第二次仍调用send。状态由[unknown, ready]变成[unknown, unknown]，合成端口调用2次、请求键2个。

**定位：** [scheduler.py][scheduler]第197行只在生成阶段检查同事项未核对结果；第246–285行的current、领取发送权和guard没有检查其他已排队实例。

**最小修复：**

- 同一事务领取发送权及实际调用前guard，复核同事项同催办的其他sending、unknown、未核对sent；已有ready也必须受约束。
- 不换请求键、不顺延过期实例、不把unknown当未发送。
- 阻塞一个事项时仍让独立事项继续，避免队列首项阻塞全部。
- 同催办判定沿用事项、目标、正文/语义与批准范围，不扩展成新产品规则。

**验收：** 先创建两个实例，再令第一条unknown；第二条发送调用为0；独立事项继续；重启仍保护；过期不得复活。

### F02｜P1：首次“收到”使同卡连续反馈和其他负责人反馈失效

**影响：** 正常“收到→预计→提交”无法走完，多人事项也只有首条反馈能更新状态。

**复现：** v1事项分配甲乙；甲收到，再甲提交报告A、乙提交报告B。applied=[1,0,0]，事项仍waiting、version=2。owner仅见首次received与反馈总数，看不到两份材料正文。期间没有owner修改、关闭或撤销。

**定位：** [am_business.py][business]第92–106行始终传原实例item_version；[action_items.py][items]第93–100行每次反馈连received都推进全局version。

**最小修复：**

- 区分事项业务决定版本与反馈流变化，或建立严格受控的卡片续接机制。
- 保留owner改变负责人、交付要求、暂停/关闭等决定的保护；不能将所有旧卡强行套到最新版本。
- 同卡同人后续预计/协助/提交、其他负责人独立反馈都能正常记录。
- owner可以查看每位负责人的有效/迟到反馈正文、材料位置、时间、来源，不能只显示数量。
- 重复点击仍幂等；收到不关闭，提交仍待核验。

**验收：** 同人连续反馈、多人反馈、重复点击，以及owner修改/关闭后的旧反馈只留证。据此离线验证即可，不为刷新卡片额外真人群发。

### F03｜P1：私聊明确引用被忽略，回答另一项目

**复现：** /project 需求75（甲，AR1甲）→/project 需求76（乙，AR2乙）→携parent_id=om1引用75问“那谁负责？”。实际答需求76/AR2乙。

**定位：** [am_service.py][service]第104–105行私聊入库未保留parent/root/thread；第48–49、171–190行依赖最近scope.focus。群链路有引用优先，私聊未复用。

**最小修复与验收：**

- 私聊保存引用/话题元数据，绑定原请求及机器人回复的ProjectRef。
- 明确引用优先；未知、过期、身份不匹配时澄清，不能退回另一个最近项目。
- 同人不同话题、跨人/群继续隔离，不让模型猜。
- 覆盖先甲后乙再引用甲、引用机器人回复、引用失效及跨身份。
- 可以与F07共用入站元数据实现，但分别保留验收。

### F04｜P1：简报未发出，变化却被视为已投递

**复现：** 09:00生成含event75的简报，预检跨60秒窗口，实例cancelled且send调用0。次日event_ids为空，正文称“没有尚未投递的变化”，旧delivery仍pending。

**定位：** [am_business.py][business]第109–117行seen包含全部投递记录；[scheduler.py][scheduler]第227–230行创建实例即写pending，第309–310行才在核验后置verified。

**最小修复：**

- 区分待投递、执行/结果未知、已验证投递；确认结果后才消费。
- 明确未发送/发前取消的事件仍待投递，进入下一次有效简报；不复活过期实例。
- unknown仍在原动作对账，不能因非verified就新发。
- 处理(subscription,event)唯一键及新实例接手，保留尝试历史。不能只加WHERE state='verified'而忽略旧pending关联。

**验收：** 发前超窗、明确未发后耗尽、unknown、verified四种；检查下一次实际生成正文，不仅检查数据库状态名。

### F05｜P2：主动简报把历史快照当作当前待办

**复现：** 第一次源有75/76，下一次完整源只有75。/todo不含76，但/briefing仍显示76的旧待办，没有历史/本次未读到提示。

**定位：** [am_service.py][service]第202–216行，briefing读当前源后，todos(reload=False)改查全量project_snapshots。

**最小修复与验收：** 以同一次成功读取集合生成当前简报，或关联catalog_current核对指纹。历史继续保留；缺行/待关联/冲突如需展示，应明确性质，不把缺行认作取消。验证todo/briefing当前集合一致。

### F06｜P1（D链路）：预检报告正文哈希与挂载契约不一致

**复现：** 真实LogicService.run_precheck→adopt→MeeglePort.commit，替换平台读取。saved_hash=a928f7…，UTF-8正文哈希=a0a153…，抛BUSINESS_CONTENT_CHANGED，平台调用0。

**定位：** [precheck.py][precheck]第6、100–103行用project_catalog.digest先JSON规范化后哈希；[meegle_port.py][meegle]第182–185行按doc_logic.digest校验UTF-8字节，两者不同。上层还可能把上传前失败显示成“结果待确认”。

**最小修复：**

- 明确分开结构化依据哈希和正文文件哈希；正文沿用doc_logic契约。
- 错算法生成的未完成预检稿失效，重新生成/采用；不静默替换已批准哈希。有实际外部动作先按记录核对。
- 有充分证据证明未上传的本地失败显示确定失败；可能已经调用平台时仍unknown，不能一律当未发送。

**验收：** 预检→采用→真实适配器合成上传/挂载/独立读回贯通；新附件正确、已知旧附件保留、审核/节点不变；普通文稿挂载保留回归。

### F07｜P2（写回开通前）：正常私聊post/首尾空白误报来源改变

**复现：** 远端消息始终未改。精确text的source_current=True；同正文post=False；首尾空白text=False。三种均能采集。

**定位：** [am_service.py][service]第72、92–112行只有群分支保存原始content指纹；私聊只留规范化strip文本。[am_updates.py][updates]第89–92行用digest({'text':q})兜底；[sheets_write_port.py][sheets]第76–84行与远端原始content比较。更正分支也受影响。

**最小修复与验收：**

- 私聊/群共用经过格式校验的原始content指纹、消息类型及来源元数据；路由规范文本和来源校验分开。
- /update更正一起修；旧记录缺可靠原指纹时重新核对，不杜撰。
- 三种未改输入检查为有效，真实更正/撤回仍使旧批准失效。
- 保持ledger_write=false，以实际适配器与合成消息验证。

### F08｜P2：空交付物清单标题被列为“已具备”

**复现：** 明确要求交付物清单，完整材料仅“交付物清单：”。实际已具备1条、缺少为空；原测试只测写了“为空”的样例。

**定位：** [precheck.py][precheck]第28–35行只看关键词命中；缺失判断依赖“为空、空白、待补”等文字。

**最小修复与验收：** 区分标题存在与实质内容。清单、正文、附件要求检查相应结构中的有效条目；无法判定放“需专业判断”。覆盖标题后空白、只有标题的DOCX、标签有但值为空的表格、实际有条目的正例。不得升级为自动专业审核。

## 四、非阻塞观察

“需求75今天更新了吗”“方案已经批准了吗”会被动作关键词误分为操作请求。可顺手改善疑问句路由，不作为额外关卡，不放宽真正写入/外发权限。

未把历史embedded全局suspended、代码风格、框架选择、全仓lint或无复现猜测列入返工。

## 五、本轮执行交接：R1-FIX1

### 接续

你是Codex执行方。用户转交本任务后，保存输入快照，读取本报告及R1 v1.0-exec，在当前真实工程核对HEAD、已修改和未跟踪文件后实施，不用旧SHA覆盖较新工作。

来源定位：用户转交源码6528b9a…、审核496d403…的A→D完成报告之后，GPT于2026-10-29给出的本审计。本窗口可复制聊天链接未取得，不编造URL。复现包为辅助材料；不能直读时可依本文八项场景构造，不因此停止可独立修复部分。

### 范围和边界

- 仅修F01—F08及必要共享入口/迁移；原v1.0-exec未冲突要求继续有效。
- 原飞书应用、唯一Python消费者、SQLite、当前本地Qwen不变；不接工作台、不新建消费者、不替换模型。
- 源码、必要迁移、隔离验证及已授权的原环境更新、脱敏回传直接推进，不逐项等批准。
- 正式ledger_write继续false，不新增受控写入窗口；不为本轮反例建立真实订阅/计划、真人群发或真实挂载。
- 原环境同范围安装/重启沿用已有有效授权；先核对运行中/未知动作。确缺授权或环境不可用仅暂停这一步，继续其余工作。
- 新真实第三方发送仍在AM中预览准确目标、正文、时间、窗口并确认；历史一次群测试不等于新增无限授权。
- 不清库、不删unknown、不覆盖数据库、不force push、不扩大原始聊天保存范围。
- 本报告未自动启动Codex或发布远端审计意见；用户验收与GPT复审按实际状态保留。

### 完成判据

| 编号 | 正确结果 |
| --- | --- |
| F01 | 首条unknown后已有第二实例不发；独立事项继续；重启/过期不复活 |
| F02 | 同人连续/多人反馈有效且owner可见明细；人工改决定后旧反馈只留证 |
| F03 | 私聊引用优先，失效引用澄清，不跨身份/话题串对象 |
| F04 | 明确未发进入下次有效简报；unknown对账；verified消费，尝试关联正确 |
| F05 | todo与briefing当前集合一致，历史缺行有准确性质 |
| F06 | 预检正文哈希一致，采用后合成挂载/读回通过，旧附件/状态保留 |
| F07 | text/post/空白来源核对正确，更正/撤回仍失效旧批准 |
| F08 | 空标题/空表格不算具备；实质条目正例、不完整读取边界正确 |

使用事件屏障、假时钟、真实SQLite、实际适配器的合成替身。检查完整调用链和用户可见输出，不只看数据库状态名。复用原有效证据；相关回归充分后停止无关扩测。Mac专属和服务账户检查由原环境按必要性复核。

迁移至少保留活跃事项、反馈、计划、批准、unknown身份；旧错误哈希稿失效；旧简报pending分清明确未发与未知；新增入站元数据仍按24小时原始聊天规则清理，业务只保留最小证据。

### 回传

仓库：Catcherog/project-workbench-review。  
路径：AM-SELF-20261029-01/R1-FIX1/。  
一个00_当前交接.md，保留R1历史，不改其他任务或全局入口。

回传八项逐项状态、最终源码/diff、必要新文件/迁移、反例转正验证、实际安装启用状态及未执行动作。分别提供完整源码SHA、审核SHA；上传前脱敏，远端固定读回后给入口。不上传私人数据库、完整聊天、凭据、真实项目原文。确有缺项只说明准确缺项，不泛问“是否继续”。

## 六、当前用户验收

可先检查/menu、/status、准确编号的/project、/todo、/changes。明确给项目编号，暂不依赖引用旧消息追问；核对来源、读取时间和预计/自报/待核验性质。

F01/F02/F04修复前暂不进入新计划真实外发、多人员反馈、自动简报验收；F05修复前不把briefing当完整当前待办。D可看采集/差异草稿，但F06/F08影响预检挂载与结论，F07需在正式写回前解决。

修复后只验受影响链路：原测试群一次准确预览批准的反馈卡、连续/多人反馈、一次明确时刻计划、本人实际订阅简报、预检与挂载。正式Sheets写回仍需具体业务事实、精确字段差异、原应用权限和受控窗口，无需为审计制造业务数据。

[handoff]: https://github.com/Catcherog/project-workbench-review/blob/496d403a69d814818cbced5e427f72ddf8aef5b2/AM-SELF-20261029-01/R1/00_%E5%BD%93%E5%89%8D%E4%BA%A4%E6%8E%A5.md
[requirements]: https://github.com/Catcherog/project-workbench-review/blob/496d403a69d814818cbced5e427f72ddf8aef5b2/AM-SELF-20261029-01/R1/inputs/AM%E6%9C%BA%E5%99%A8%E4%BA%BA%E5%9B%9B%E6%89%B9%E5%AE%9E%E6%96%BD%E6%8C%87%E4%BB%A4.md
[manifest]: https://github.com/Catcherog/project-workbench-review/blob/496d403a69d814818cbced5e427f72ddf8aef5b2/AM-SELF-20261029-01/R1/05_%E7%89%88%E6%9C%AC%E4%B8%8E%E6%96%87%E4%BB%B6%E6%B8%85%E5%8D%95.json
[diff]: https://github.com/Catcherog/project-workbench-review/blob/496d403a69d814818cbced5e427f72ddf8aef5b2/AM-SELF-20261029-01/R1/changes.patch
[validation]: https://github.com/Catcherog/project-workbench-review/blob/496d403a69d814818cbced5e427f72ddf8aef5b2/AM-SELF-20261029-01/R1/03_%E5%88%86%E5%B1%82%E9%AA%8C%E8%AF%81%E8%AE%B0%E5%BD%95.md
[service]: https://github.com/Catcherog/project-workbench-review/blob/496d403a69d814818cbced5e427f72ddf8aef5b2/AM-SELF-20261029-01/R1/source/local-qwen3.8/feishu-bridge/am_service.py
[business]: https://github.com/Catcherog/project-workbench-review/blob/496d403a69d814818cbced5e427f72ddf8aef5b2/AM-SELF-20261029-01/R1/source/local-qwen3.8/feishu-bridge/am_business.py
[updates]: https://github.com/Catcherog/project-workbench-review/blob/496d403a69d814818cbced5e427f72ddf8aef5b2/AM-SELF-20261029-01/R1/source/local-qwen3.8/feishu-bridge/am_updates.py
[sheets]: https://github.com/Catcherog/project-workbench-review/blob/496d403a69d814818cbced5e427f72ddf8aef5b2/AM-SELF-20261029-01/R1/source/local-qwen3.8/feishu-bridge/sheets_write_port.py
[groupai]: https://github.com/Catcherog/project-workbench-review/blob/496d403a69d814818cbced5e427f72ddf8aef5b2/AM-SELF-20261029-01/R1/source/local-qwen3.8/feishu-bridge/group_ai.py
[scheduler]: https://github.com/Catcherog/project-workbench-review/blob/496d403a69d814818cbced5e427f72ddf8aef5b2/AM-SELF-20261029-01/R1/source/FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/fs_agent/scheduler.py
[items]: https://github.com/Catcherog/project-workbench-review/blob/496d403a69d814818cbced5e427f72ddf8aef5b2/AM-SELF-20261029-01/R1/source/FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/fs_agent/action_items.py
[ledger]: https://github.com/Catcherog/project-workbench-review/blob/496d403a69d814818cbced5e427f72ddf8aef5b2/AM-SELF-20261029-01/R1/source/FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/fs_agent/ledger_changes.py
[precheck]: https://github.com/Catcherog/project-workbench-review/blob/496d403a69d814818cbced5e427f72ddf8aef5b2/AM-SELF-20261029-01/R1/source/FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/fs_agent/precheck.py
[meegle]: https://github.com/Catcherog/project-workbench-review/blob/496d403a69d814818cbced5e427f72ddf8aef5b2/AM-SELF-20261029-01/R1/source/FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/fs_agent/meegle_port.py
[model]: https://github.com/Catcherog/project-workbench-review/blob/496d403a69d814818cbced5e427f72ddf8aef5b2/AM-SELF-20261029-01/R1/source/FS-AGENT-GROK-POC-20261017-01_R1_Studio/src/fs_agent/model_coordinator.py
