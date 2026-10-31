# AM 三模块统一版本：六个问题的离线复现

本包运行 5 个脚本，复现 6 个已确认问题。**脚本成功退出、assert 成立，表示缺陷现状被复现，不表示产品检查通过，也不表示问题已经修复。** 本包不修源码，不安装依赖，不调用真实模型或平台，不读取真实账号配置。

## 对应版本

| 对象 | 固定身份 |
| --- | --- |
| 统一审核提交 | `581632802f415b923e17ccf4817a153ac630de5c` |
| 交接声明的原工程源码提交 | `53330c3869aa1ff4e39c7c41ec82243c6126491f` |
| 原对话 R1 审核基础 | `7445333757fd39b674caa7cca8237ee9ecc46f89` |

已验证的重建方法：先取基础提交中 `AM-CONVERSATION-20261030-01/R1/source/`，再叠加统一审核提交中 `AM-CONVERSATION-20261030-01/R1/coordination/20261031/source/`。不要把本次增量目录独立当作完整工程。

验证只针对以上固定内容。`source-fingerprints.json` 记录复现涉及的主要源码及测试素材指纹，runner 会核对运行前后指纹。对其他版本的运行结果必须另行解释；断言不再成立可能表示已修复，也可能是接口、前置条件或运行环境变化，不能直接据此宣布修复通过。

## 运行

需要 Python 3.12 或以上版本和被审工程源码，与原宿主工程的版本要求一致。本包自身只使用 Python 标准库，不需要 pytest；本次实际运行版本为 Python 3.12.14。环境变量指向包含以下三个目录的工程根：

- `FS-AGENT-GROK-POC-20261017-01_R1_Studio/`
- `am-conversation-r1/`
- `local-qwen3.8/`

```bash
export AM_AUDIT_SOURCE_ROOT='/absolute/path/to/reconstructed-source'
python /absolute/path/to/repro-package/run_repros.py
```

默认生成本包目录下的 `repro-results.json`。也可指定位置：

```bash
python /absolute/path/to/repro-package/run_repros.py --output /tmp/am-repro-results.json
```

单独运行某脚本时同样需要上述环境变量；请勿使用 `python -O`，因为它会关闭断言。runner 退出码 0 表示六个缺陷在指纹匹配的源码上全部复现；其他退出码需要检查结果中的具体原因。

## 六个问题及脚本

| 编号 | 优先级 | 现状缺陷 | 复现脚本 |
| --- | --- | --- | --- |
| F01 | P1 | 来源先被拒绝，后续普通读取错误使旧事实恢复可见 | `am_information_audit_repro.py` |
| F02 | P1 | 已撤权来源仍由旧助手回复进入模型历史并可再次输出 | `reproduce_conversation_history_revocation.py` |
| F03 | P1 | 一个不能读取的发现队首反复重试，后续正常子项未获处理 | `am_information_audit_repro.py` |
| F04 | P1 | 本次云写入结果未知，却用同版本旧动作的成功回执确认 | `repro_doc_receipt_mix.py` |
| F05 | P2 | 同一来源追加项目 B 关联后，没有重新提取 B 的事实 | `am_information_subject_repro.py` |
| F06 | P2 | 指定 A 稿修改预检要求，底层实际修改最新 B 稿 | `repro_doc_wrong_draft.py` |

## 真实实现和替身的界限

| 复现范围 | 实际执行的被审实现 | 合成或替代部分 |
| --- | --- | --- |
| F01 / F03 | 信息 Store、SyncEngine、FactEngine，以及 Discovery 的队列方法 | adapter 返回值、权限错误、业务子项读取；通过 `Discovery.__new__` 避开安装真实适配器的初始化 |
| F02 | 信息库、ConversationStore、信息投影函数和 ConversationAgent 的完整本地调用链 | 固定身份、当前项目查询桥接和确定性模型；替身模型重复已看到的助手历史，证明宿主输入与输出校验允许该行为，不代表每次真实 Qwen 都会这样回答 |
| F04 | NativePublisher.save、DocumentTools.publish 和实际 SQLite 写入日志 | 内存云端、预览与草稿查找入口；修订语义复核由合成回调代替；不执行真实文档生成或真人批准 |
| F05 | InformationService、EntityCatalog、Discovery.register_document、同步及提取队列 | 云文档解析回执和确定性提取器；提取器只按真实接口给出的允许项目范围提取 |
| F06 | LogicService、预检要求方法、DocumentTools.edit 和 SQLite | 合成 owner、临时配置根、身份与指定草稿查找；不读取真实文档业务配置 |

F04 使用标准库 AST 从被审工程的 `tests/test_document_standards.py` 中仅摘取 `fixture_native` 和 `profile_and_slots` 两个函数，作为公开合成模板素材。没有导入或执行该测试模块的顶层内容，不导入 pytest，不运行其测试集合。所调用的 `blueprint` 仍是被审实现。

所有业务实例只使用内存数据库或临时目录。`_bootstrap.py` 在导入业务实现前切换到临时工作目录、关闭字节码写入，并阻止网络套接字、DNS 和外部进程启动。`run_repros.py` 本身只通过本机 Python 启动这五个脚本。涉及 `fs_agent.config` 等模块时只导入其类和定义；不会装载用户实际账号、应用、模型或平台配置。源码目录只读，包目录只新增结果文件。

## 与整轮验证数量的关系

本轮另有同组 **31 项独立复跑**，以及本包的 **6 个缺陷复现**；两者不是“37 项产品验收通过”。完整审计结论见随包的 `AUDIT_AND_HANDOFF.md`。

交接报告中的 **83 项联合检查**，本轮核对了远端 XML、用例名称及版本证据；当前审计环境缺少 pytest，没有独立复跑这 83 项。本包不将这些远端结果或已知缺陷断言计为新的通过数，也不替代真实 Qwen、飞书、手机和真人业务验收。
