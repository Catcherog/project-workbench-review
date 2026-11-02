# R3 接入原 AM 的执行设计

## 现状与本轮停止点

从原机当前工作树增量接入，固定参考为 `aab37396ea86b6e742eed79369583801664d1f35`；已有后续修改必须保留。本包是可运行组件和接入设计，不是已安装补丁。原 `response=legacy`、旧重写 off、`goal_tracking=false`、原 Qwen、唯一消费者、600秒身份、`ledger_write=false` 保持。

关键接口依据见固定版本 [ConversationAgent](https://github.com/Catcherog/project-workbench-review/blob/9ef8076b32ecb5800c70a4f531fa2a859fb6c790/AM-HARNESS-20261031-01/R2-FIX2/source/am-conversation-r1/src/am_conversation/engine.py) 与 [ResponsePipeline](https://github.com/Catcherog/project-workbench-review/blob/9ef8076b32ecb5800c70a4f531fa2a859fb6c790/AM-HARNESS-20261031-01/R2-FIX2/source/am-conversation-r1/src/am_response/pipeline.py)。不要为取得 Outcome 而直接开启旧 enforce；那会同时启用旧协议、固定来源前缀和旧保护文案。

## 1. 单独采集最终业务结果

旧 `ResponsePipeline.begin` 在 legacy 下返回 None，因此当前默认配置没有可供新模块使用的活动响应快照。新增**只采集、不改变旧回复**的 Outcome collector，使用独立 ContextVar，复用原结果适配、回执绑定和完成检查；正常请求结束时 reset。

在实际工具结果、原控制结果、查询快照和缓存回执返回处增加 collector.record hook。缓存命中记录原调用身份，不重新包装参数。不可通过额外查询或再次创建来补齐表达证据；无法投影的结果记录为不支持，保留原回复。

特别注意：**collector token 与旧 response protocol token 必须分离。**旧代码根据 response token 是否存在调用 `model.set_response_protocol`。若把新 collector token 传进去，会在 legacy 配置下意外要求模型输出旧 `response_plan`。本轮只让业务结果进入新 collector，不改变任务模型原协议。

最终 reply 确定后才冻结 Outcome，生成候选期间不再改写其 hash。投影器须消费实际语义限定、每项完成证据和待补缺口。`integration.py` 已要求显式提供 `outcome_getter`、`require_current` 回调；原机须把它们绑定到独立 collector 的当前快照与有效性检查，不能假定 legacy 已有活动 state。

## 2. 宿主投影与真实模型回调

| 接口 | 原机必须提供的内容 | 不能用什么替代 |
| --- | --- | --- |
| `frame_projector(envelope)` | 绑定原事件、scope、源码来源修订、取消/任务修订、到期；核实原子事实与每项原生回执 | 模型自报成功、直接把原始资料段落标成事实 |
| collector 的当前快照 getter | 重新取得当前有效 Outcome，供调用前后比较 | 给旧候选补新 hash |
| 原 ModelCoordinator 回调 | 同消费者、同模型租约、共享deadline、取消和停止确认 | 主服务旁再开一个直连 Ollama 消费者 |
| 发送前 guard | 原权限、来源版本、revision、cancel_epoch、generation 与 outbox 边界检查 | 仅在生成前检查一次 |

`SpeechFrame` 的 trusted/verified 字段是可信宿主合同，不是本模块对平台事实的独立证明。投影器必须沿用 R2-FIX2 的原操作记录核对；同原生创建对象不满足两个独立目标。失败原因只能用已知原因，未知保持未知。

当前代码会拒绝未投影的范围、时间、极性等字段。执行端应把它们完整组织为原子命题后传入，并保留原始来源；不能删掉字段来绕过拒绝。批准正文与链接采用精确片段，一般状态用结构化语义重新表达。

## 3. 末端调用位置、快查询与预算

普通主循环在 `_finish` 保存历史之前调用 `prepare_terminal_reply`，只调整 reply.text，业务状态和真实回执不改。生成最多一次，调用后重新核对来源和任务状态；通过才进入原历史/投递流程。

快查询有两条路径，均须显式传 `fastpath=True`：独立 `handle_fastpath`，以及普通 `handle` 内命中的 fastpath 分支。不能只保护前者。快查询用宿主自然模板，无模型、无额外等待。

普通 `handle` 的 `model.set_deadline` 在 `_finish` 返回后才 reset，可传递同一个 monotonic deadline。独立快查询没有该 deadline。`expires_at` 是资料有效期，不能当作模型剩余时间；没有共享 deadline 就跳过模型。表达预算取配置上限与任务剩余预算减发送预留的较小值，迟到结果弃用。

`StopUnconfirmed` 必须回到原协调器核对，不能当作已停止释放模型通道。权限、来源或取消失效直接中止，禁止 fallback 发送过期内容。发送前再次调用 `gateway_text/recheck_before_send` 并进入原 outbox 原子边界；prepared、已入队、平台接收、回读成功分开记账。

## 4. 验证、对照与训练顺序

先运行本包离线检查与演示，再在原机实现 collector/projector/协调器回调，做相同冻结事实的 shadow 对照。对照脚本中的独立 Ollama 仅供已核实的隔离实例，不能指向生产端口；Codex CLI 先核实实际版本、配置与工具面，保留自带策略/AGENTS，不把它描述成裸模型。

随后补齐原48项私有配对，只读取相关评分材料，校验现有 dataset hash；不要重建随机键再冒充原配对。新的自由候选先用小批人评建立绝对合格标准与偏好。正式gold出口保持人审条件；大批机器筛选候选另走显式experimental_silver SFT，保留弱监督身份。缺少真实评审证据时对应出口保持空。

准备隔离 SFT/DPO 时，原机读取模型元数据、原始权重来源、tokenizer/chat template、芯片和内存。先过数据/权重/依赖预检，再做小规模 smoke run；DPO reference 保持 SFT 状态固定。训练后在未参与调参的独立场景复测事实、风格、延迟，再量化导出，并重新验证量化后的结果。训练 loss 降低、脚本退出0均不能代替这些验收。

## 5. 回传内容与启用边界

回传本轮实际改动、最终源码SHA、数据/政策/Prompt版本、真实退出码、原机资源核对、各对照组原始结果、缺失/拒绝/超时、人工评分与未完成边界。保留旧288条、123资格分母、首轮盲评和27项既有失败，不重写旧成绩、不把复跑重复累计。

本轮当前授权已扩展到设计、代码、合成候选及需要时的隔离训练尝试；不能拿旧R1“不训练”阻塞已获授权的工作。真实资源尚未核实时先完成预检和可复现准备，不虚报已训练。远程付费资源、生产切换、扩大业务外发和整体启用另按已有有效授权及具体结果处理，本包没有执行这些动作。
