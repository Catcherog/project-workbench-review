# R1 需求—实现—证据覆盖表

这些编号用于追溯，不相加为测试数量。每个测试脚本中的场景和断言详见公开源码及最终验证日志。旧P1业务规则保留；新的候选纳入、输入原件保留和不同报告分别发送已更新相应回归断言。

## P1 与共同规则

G-01—G-21沿用原对象/身份/布局/权限/运行规则，新增路径分别在下表、七条原则及实现说明定位。P1的原日期、保存、撤销交互由s1p1-domain、s1p1-http、s1p1-browser及fix1-domain重新验证。初始资料验收结论未被改写。

## AT-01—48

| 编号 | 必须观察的业务结果 | 实现 | 验证入口 | 范围限制 |
|---|---|---|---|---|
| AT-01 | 记录用户报告的行动、等待结果和具体检查时间；不实际代发、不假造发送凭证；不强迫再填完成时间 | `scripts/core-input.mjs`、`scripts/codex-assistant.mjs`、`lib/work-items.ts` | core-input、core-browser、s1p1-domain | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-02 | 保存原图与有来源进展并更新原事项；他人反馈不冒称系统核实，预测不覆盖经理要求 | `scripts/core-input.mjs`、`scripts/codex-assistant.mjs`、`lib/work-items.ts` | core-input、core-browser、s1p1-domain | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-03 | 只理解资料，不把引用内容当用户授权；纯讨论不建正式安排或外部对象 | `scripts/core-input.mjs`、`scripts/codex-assistant.mjs`、`lib/work-items.ts` | core-input、core-browser、s1p1-domain | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-04 | 全新事项先候选；同名归属不足只做必要消歧；用户明确要求本地创建不重复问纳入 | `scripts/core-input.mjs`、`scripts/codex-assistant.mjs`、`lib/work-items.ts` | core-input、core-browser、s1p1-domain | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-05 | 保留一个整体跟进事项，内部记录步骤责任；已完成部分不重复催，不拆出多条催办 | `scripts/core-input.mjs`、`scripts/codex-assistant.mjs`、`lib/work-items.ts` | core-input、core-browser、s1p1-domain | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-06 | 分别更新正确事项，保留共同来源；后续飞书分别发，不因共同来源而混成一件事 | `scripts/core-input.mjs`、`scripts/codex-assistant.mjs`、`lib/work-items.ts` | core-input、core-browser、s1p1-domain | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-07 | 按原消息时点解析可读日期、保留顺序及范围；关键缺口不猜；已知事实可先保存 | `scripts/core-input.mjs`、`scripts/codex-assistant.mjs`、`lib/work-items.ts` | core-input、core-browser、s1p1-domain | 多图顺序及原消息时间路径已验证；未单独扩充裁剪图的真实模型样本 |
| AT-08 | 重复证据不建重复事项／安排；真正的新时间指令仍处理；保留版本和来源 | `scripts/core-input.mjs`、`scripts/codex-assistant.mjs`、`lib/work-items.ts` | core-input、core-browser、s1p1-domain | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-09 | 引用映射原事项，先读最新状态；更新同一事项，不恢复旧时间、不重复建项 | `scripts/core-feishu-input.mjs`、`scripts/work-item-entry.mjs`、`lib/work-item-progress.ts` | core-feishu、core-input、s1p1-http、s1p1-browser、core-work-agent | 真实事件桥和持久化在模拟通道中验证；真实引用收发闭环未执行 |
| AT-10 | 分别显示接收和未处理范围；不误改对象，保留输入并最小消歧；不把接收当保存成功 | `scripts/core-feishu-input.mjs`、`scripts/work-item-entry.mjs`、`lib/work-item-progress.ts` | core-feishu、core-input、s1p1-http、s1p1-browser、core-work-agent | 真实事件桥和持久化在模拟通道中验证；真实引用收发闭环未执行 |
| AT-11 | 业务结果、权限、时间和来源一致，回读到同一身份；不同入口不各有一套规则 | `scripts/core-feishu-input.mjs`、`scripts/work-item-entry.mjs`、`lib/work-item-progress.ts` | core-feishu、core-input、s1p1-http、s1p1-browser、core-work-agent | 真实事件桥和持久化在模拟通道中验证；真实引用收发闭环未执行 |
| AT-12 | 前者保留输入并说明未保存；后者说明已保存／刷新失败，不诱导重复业务提交 | `scripts/core-feishu-input.mjs`、`scripts/work-item-entry.mjs`、`lib/work-item-progress.ts` | core-feishu、core-input、s1p1-http、s1p1-browser、core-work-agent | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-13 | 明确事实先保存并留场讨论；未确认建议不执行；纯记录成功则按 P1 回原列表并保留位置 | `scripts/core-feishu-input.mjs`、`scripts/work-item-entry.mjs`、`lib/work-item-progress.ts` | core-feishu、core-input、s1p1-http、s1p1-browser、core-work-agent | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-14 | 保留新人工决定，旧输出不覆盖；新证据可留存或提出建议，不自动逆转 | `scripts/core-feishu-input.mjs`、`scripts/work-item-entry.mjs`、`lib/work-item-progress.ts` | core-feishu、core-input、s1p1-http、s1p1-browser、core-work-agent | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-15 | 涉及内容被后续修改时阻止整次撤销，不产生部分撤销；成功纠正／撤销后按 F-C03 复核自动结果，保留较新人工决定和已发送事实 | `scripts/core-feishu-input.mjs`、`scripts/work-item-entry.mjs`、`lib/work-item-progress.ts` | core-feishu、core-input、s1p1-http、s1p1-browser、core-work-agent | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-16 | 原输入及已取得事实保留，未完成范围可见；不假报分析完成或全量已读，不默认换模型 | `scripts/core-feishu-input.mjs`、`scripts/work-item-entry.mjs`、`lib/work-item-progress.ts` | core-feishu、core-input、s1p1-http、s1p1-browser、core-work-agent | 原图失败、预算等待、取消和模型超时保留输入；各失败原因分别记录 |
| AT-17 | 前两次计数为 1、2，第三次成功提醒时临时升一级；P3→P2、P2→P1、P1保持P1，不能进P0 | `lib/work-item-core.ts`、`scripts/work-item-core-service.mjs`、`scripts/followup-notifications.mjs` | core-p1-p5、core-runtime、core-input | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-18 | 保留已回复事实，不清零、不停催、不追问原因；无新增信息不等于外部无变化 | `lib/work-item-core.ts`、`scripts/work-item-core-service.mjs`、`scripts/followup-notifications.mjs` | core-p1-p5、core-runtime、core-input | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-19 | 连续未有效处理计数清零；下一次有效提醒从 1 开始；催办继续，已有纯催办临时升级暂不恢复 | `lib/work-item-core.ts`、`scripts/work-item-core-service.mjs`、`scripts/followup-notifications.mjs` | core-p1-p5、core-runtime、core-input | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-20 | 有效时间覆盖当前后续需要时暂缓常规催办，按条件恢复纯催办等级；不强迫补检查时间 | `lib/work-item-core.ts`、`scripts/work-item-core-service.mjs`、`scripts/followup-notifications.mjs` | core-p1-p5、core-runtime、core-input | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-21 | 首次产生与用户报告同等业务效果，不要求重复确认；重复旧证据不连续重置计数 | `lib/work-item-core.ts`、`scripts/work-item-core-service.mjs`、`scripts/followup-notifications.mjs` | core-p1-p5、core-runtime、core-input | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-22 | 同一未妥善处理需要不再升一级；只有新的需要或此前已妥善处理后再次产生介入需要才进入新轮次 | `lib/work-item-core.ts`、`scripts/work-item-core-service.mjs`、`scripts/followup-notifications.mjs` | core-p1-p5、core-runtime、core-input | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-23 | 恢复不得覆盖新的真实业务等级或人工决定；人工改级本身不等于已处理业务 | `lib/work-item-core.ts`、`scripts/work-item-core-service.mjs`、`scripts/followup-notifications.mjs` | core-p1-p5、core-runtime、core-input | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-24 | 失败未知不计为第三次有效提醒、不靠尝试触发升级；成功回执可核后最多计一次，迟到结果保护新人工决定 | `lib/work-item-core.ts`、`scripts/work-item-core-service.mjs`、`scripts/followup-notifications.mjs` | core-p1-p5、core-runtime、core-input | 真实事件桥和持久化在模拟通道中验证；真实引用收发闭环未执行 |
| AT-25 | 按9:00／14:00、9:00、最后实际工作日14:00、每日9:00各自规则复查；有效等待和暂停优先，不强迫造日期 | `lib/work-calendar.ts`、`lib/work-item-core.ts`、`scripts/work-item-core-service.mjs` | core-p1-p5、core-runtime、core-browser | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-26 | 按实际配置判断周度落点，不写死周五或双休日；无来源报告具体配置缺口，不猜日历或改截止要求 | `lib/work-calendar.ts`、`lib/work-item-core.ts`、`scripts/work-item-core-service.mjs` | core-p1-p5、core-runtime、core-browser | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-27 | 延至下个实际工作日9:00；事实照常更新；纯催办升到P1不能突破免打扰 | `lib/work-calendar.ts`、`lib/work-item-core.ts`、`scripts/work-item-core-service.mjs` | core-p1-p5、core-runtime、core-browser | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-28 | 既定例外及时通知；日期级默认10:00与其他明确时刻不被9／14常规提醒批量改写 | `lib/work-calendar.ts`、`lib/work-item-core.ts`、`scripts/work-item-core-service.mjs` | core-p1-p5、core-runtime、core-browser | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-29 | 同轮合一条并最多计一次，不同事项分别发；下一周期符合条件可再次提醒，不被永久去重 | `lib/work-calendar.ts`、`lib/work-item-core.ts`、`scripts/work-item-core-service.mjs` | core-p1-p5、core-runtime、core-browser | 真实事件桥和持久化在模拟通道中验证；真实引用收发闭环未执行 |
| AT-30 | 默认下个实际工作日9:00恢复，明确指令优先；暂停期不计数；恢复先核实，不回放旧提醒 | `lib/work-calendar.ts`、`lib/work-item-core.ts`、`scripts/work-item-core-service.mjs` | core-p1-p5、core-runtime、core-browser | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-31 | 恢复后第一次有效提醒从1计数，原升级保留且同轮不能再升一级；暂停不当作解决 | `lib/work-calendar.ts`、`lib/work-item-core.ts`、`scripts/work-item-core-service.mjs` | core-p1-p5、core-runtime、core-browser | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-32 | 前者及时补一次当前提醒，不等下一固定时段；后者不补旧催办；漏发不计数、不回放多条 | `lib/work-calendar.ts`、`lib/work-item-core.ts`、`scripts/work-item-core-service.mjs` | core-p1-p5、core-runtime、core-browser | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-33 | 只保护纳入决定；记录与自动结束不额外审批，除非已有要求该事项关闭须人工审核 | `lib/work-item-core.ts`、`lib/work-items.ts`、`app/work-item-core-controls.tsx` | core-p1-p5、core-runtime、core-input | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-34 | 可记录事实并提出重开请求，待审期间不先重开；AI代执行关闭不改变决定属人工 | `lib/work-item-core.ts`、`lib/work-items.ts`、`app/work-item-core-controls.tsx` | core-p1-p5、core-runtime、core-input | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-35 | 新依据可在权限内修正并保留原决定；重复旧证据不能重新打开，不能顺带完成正式节点 | `lib/work-item-core.ts`、`lib/work-items.ts`、`app/work-item-core-controls.tsx` | core-p1-p5、core-runtime、core-input | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-36 | 工作日9:00复查、仍必要逐事项提示；沉默不批准；其他授权内更新继续；明确延后／暂停有效 | `lib/work-item-core.ts`、`lib/work-items.ts`、`app/work-item-core-controls.tsx` | core-p1-p5、core-runtime、core-input | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-37 | 首次即时提示，后续按工作日9／14跟进，新实质紧急变化可另提示；不自动改P0，不每小时无条件追问 | `lib/work-item-core.ts`、`lib/work-items.ts`、`app/work-item-core-controls.tsx` | core-p1-p5、core-runtime、core-input | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-38 | 指令本身即确认，不重复审批；不固定催办，只在实质变化、明确检查或新决策需要时通知 | `lib/work-item-core.ts`、`lib/work-items.ts`、`app/work-item-core-controls.tsx` | core-p1-p5、core-runtime、core-input | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-39 | 前者工作日9:00复查逐事项提示，不自动纳入或临时升级；后者不按旧规则重复问 | `lib/work-item-core.ts`、`lib/work-items.ts`、`app/work-item-core-controls.tsx` | core-p1-p5、core-runtime、core-input | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-40 | 自动撤下待确认队列、留依据并告知已解决无需纳入；遵循免打扰；不因未回复重问或升级 | `lib/work-item-core.ts`、`lib/work-items.ts`、`app/work-item-core-controls.tsx` | core-p1-p5、core-runtime、core-input | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-41 | 及时说明本次尚未核实，同故障不刷屏；不认定责任人未交付、不计业务催办升级；恢复后补结论 | `scripts/work-item-core-service.mjs`、`lib/core-reconcile.ts`、`scripts/core-collaboration.mjs`、`scripts/local-store.mjs` | core-runtime、core-chain、core-p1-p5、core-feishu、feishu-sync-service | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-42 | 先按事件实际时间更新并停催；延后通知发送前重查，不发失效已完成；新状态遵守重开权限 | `scripts/work-item-core-service.mjs`、`lib/core-reconcile.ts`、`scripts/core-collaboration.mjs`、`scripts/local-store.mjs` | core-runtime、core-chain、core-p1-p5、core-feishu、feishu-sync-service | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-43 | 区分读取、保存、发送状态；工作台可见未送达；未知先查，不盲目重复发送，文案生成不等于成功 | `scripts/work-item-core-service.mjs`、`lib/core-reconcile.ts`、`scripts/core-collaboration.mjs`、`scripts/local-store.mjs` | core-runtime、core-chain、core-p1-p5、core-feishu、feishu-sync-service | 真实事件桥和持久化在模拟通道中验证；真实引用收发闭环未执行 |
| AT-44 | 检查完成不关闭事项；保留有效要求或时间待确认／明确待定真实状态，按等级复查，不追问原因、不虚构闭环 | `scripts/work-item-core-service.mjs`、`lib/core-reconcile.ts`、`scripts/core-collaboration.mjs`、`scripts/local-store.mjs` | core-runtime、core-chain、core-p1-p5、core-feishu、feishu-sync-service | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-45 | 原日期、要求与逾期事实保留；预测和跟进另记，不用自动顺延消除逾期 | `scripts/work-item-core-service.mjs`、`lib/core-reconcile.ts`、`scripts/core-collaboration.mjs`、`scripts/local-store.mjs` | core-runtime、core-chain、core-p1-p5、core-feishu、feishu-sync-service | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-46 | 按现行规则记录工程师交付，不增加PM二次内容验收；本地结束不代替专业审批、节点完成或正式写入 | `scripts/work-item-core-service.mjs`、`lib/core-reconcile.ts`、`scripts/core-collaboration.mjs`、`scripts/local-store.mjs` | core-runtime、core-chain、core-p1-p5、core-feishu、feishu-sync-service | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-47 | 显示最后成功检查和覆盖缺口，不虚构次数、全天候检查或硬预算封顶；恢复按最新状态而非积压回放 | `scripts/work-item-core-service.mjs`、`lib/core-reconcile.ts`、`scripts/core-collaboration.mjs`、`scripts/local-store.mjs` | core-runtime、core-chain、core-p1-p5、core-feishu、feishu-sync-service | 合成数据/时钟/适配器；不代表真实外发或业务验收 |
| AT-48 | 报告只限相应证据层级；不得宣称真实引用闭环、远端业务已完成或功能已由用户验收 | `scripts/work-item-core-service.mjs`、`lib/core-reconcile.ts`、`scripts/core-collaboration.mjs`、`scripts/local-store.mjs` | core-runtime、core-chain、core-p1-p5、core-feishu、feishu-sync-service | 真实事件桥和持久化在模拟通道中验证；真实引用收发闭环未执行 |

## 七条跨阶段原则

| 编号 | 行为 | 实现 | 验证 |
|---|---|---|---|
| F-C01 | 逐项批准与独立纳入，允许部分决定 | scripts/core-collaboration.mjs | core-p1-p5; core-chain |
| F-C02 | 发前重读目标，失效停止、变化重预览、未知查询 | scripts/core-collaboration.mjs; lib/core-reconcile.ts; scripts/feishu-sync.mjs | core-chain; core-runtime; feishu-sync-service |
| F-C03 | 整次冲突撤销与派生复核，保留较新决定和已发事实 | lib/work-item-progress.ts; lib/work-items.ts; lib/work-item-core.ts; lib/core-reconcile.ts | s1p1-domain; core-input; core-runtime |
| F-C04 | 具体消息执行权接手/交回，未知仍查询 | scripts/core-collaboration.mjs | core-p1-p5 |
| F-C05 | 责任步骤与本人计数分开，同事反馈无本人授权 | lib/work-item-core.ts; scripts/core-input.mjs; scripts/core-feishu-input.mjs | core-p1-p5; core-feishu |
| F-C06 | 仅复核有原文依据的依赖，独立授权和结束 | lib/work-item-dependencies.ts; lib/core-reconcile.ts | core-p1-p5; core-chain |
| F-C07 | 完整链分层验证，不把模拟或人工补完当真实完成 | scripts/test-core-chain.mjs; scripts/test-core-real.mjs; scripts/replay-core-real.mjs | core-chain; real-model-results; real-model-replay |

## P4/P5 与整体审查映射

| 原编号 | 实际落点与证据 |
|---|---|
| C45-01—13、P4-A01—08 | work-item-dependencies、core-work-agent及core-reconcile；core-p1-p5、core-chain、真实模型输出与修复后重放。C45-12是历史文档交接事项，不新增运行功能。 |
| C5-01—06、C5-10—15、C5-20—21 | work-item-collaboration准备模板、材料、责任人/提供方/所有者路径及冲突；读取实际关联与交付审核，不代写或代关联；core-p1-p5及core-chain。 |
| C5-07—09、C5-16—19、C5-22 | core-collaboration及原reminderRun，完整消息、部分批准、人工接手、失效、失败/未知回读、不同目标分别发送；core-browser、core-p1-p5、core-feishu。 |
| V2-01—16、V3-04—08 | 依赖、范围/共享、时长/窗口、协调/影响共享、本人介入；按上述P4证据复用，不新增一套计数。真实模型曾把范围共享误判为影响知晓，控制层已修复，原失败和重放证据均保留。 |
| V2-17—40、V3-01—03 | 资料与模板、角色路径、完整预览、批量保留项、失败/未知、独立本人信息；按上述P5及F-C证据复用。 |
| X-01—08、I-01—06 | 作为跨阶段一致性检查映射，落实到联合确认、同事项步骤、回执计数、撤销联动、发前复核及范围存在/已共享区分，不把审查建议新增为用户批准。 |

## 实际未完成与边界

- 真实测试项目待唯一选择；三个候选已读取，未写入。真实测试项目主链、真实收发引用和接收人可见性仍未验证。
- 实际工作日历未在本轮代用户配置到正式环境；规则只用明确标为合成的日历验证。
- 真实接收人映射、角色和节点关系必须在实际对象上核对；UI提供查询与缺口显示，不按名称猜测。
- 已验证真实CLI身份及发送dry-run结构；dry-run不是发送或送达。没有消息ID且实际通道无请求键查询能力时，未知记录保留，不重发。
- 模型故障历史与语义错误保留；真实模型重放证明控制层修复，不冒充修复后又调用了一次模型。
- 正式安装、生产迁移、真实启用、产品源码push/merge和用户验收未执行。
