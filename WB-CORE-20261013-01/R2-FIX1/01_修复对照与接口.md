# 两项缺陷的增量修复

## R1-B01

原路径在创建 `reopenProposal` 后，被 `closed(row)` 提前退出挡住。只删除这道拦截仍不足以满足要求：旧检查时间、P0 建议、恢复补提醒及旧延期槽可能抢先进入普通业务分支，第一通道取得回执后第二通道又会被关闭状态挡住。

本轮处理：

- `coreReopenProposal` 只返回仍关闭、来源引用有效、没有较新关闭／重开决定的具体建议。投影与通知共同使用这个判断。
- 已关闭且仍待审时走独立的每日 9:00 审核时段，再通过原实际日历、暂停及免打扰检查；没有待审的关闭事项保持安静。关闭事项的旧明确检查、P0 事件与旧普通延期不被重新激活。开放事项原紧急/P0逻辑保留。
- 审核通知保持 `kind=review`、`counts=false`，回执不改变关闭状态，也不因沉默自动批准。双通道沿用同事项同轮去重；第二通道只在同一重开建议仍有效时续发。发送间证据撤回则停止未发通道。通知身份绑定具体重开建议；建议被替换时，旧正文不能借同一每日时段继续发送。
- 本人重开／重新办结／忽略／新变化决定，或新证据确认已无剩余动作时清理待审建议并保留历史；撤回或更正导致证据失效时不再提示旧决定。

改动位于 `lib/work-item-core.ts`、`lib/work-items.ts` 和 `scripts/work-item-core-service.mjs`。没有增加自动批准或新的业务对象。

## R1-B02

原逻辑只排除 `running`，同事输入随后一律返回 `saved`。本轮先读取当前及原输入重试历史对应的持久化 `core-input`／`work-item` 回执，核对输入身份、实际改动以及未撤销状态。单有任务缓存里的 saved、不存在业务回执，不能证明保存。

`POST /api/v2/core` 的 `action=input-receipt` 对同事输入返回以下独立字段；本人私聊回执分支未改：

| 字段 | 含义 |
| --- | --- |
| `status` | 当前综合状态：saved、processing、budget_wait、failed、cancelled、interrupted、clarify、discuss、unread、withdrawn 或 not_saved。 |
| `inputStatus` | 原始输入封装的处理状态。 |
| `jobStatus` | 当前模型任务状态；可能在 saved 时仍为 running 或 cancelled。 |
| `save.status` / `save.receipt` | 业务事实是否持久化；只有真实保存时附业务回执。 |
| `outcome` | 理解与落账结果；回执缺失或撤销时不再沿用缓存中的 saved。 |
| `preparation` | 后段依赖／资料准备状态和失败原因；后段未完成不抹掉前段保存。 |
| `failureCode` / `error` | 当前任务的失败依据；后段故障另见 preparation。 |

典型结果：预算不足且没有落账 → budget_wait/not_saved；保存前取消 → cancelled/not_saved；只有讨论或待澄清 → discuss/clarify + not_saved；前段落账、后段超时／取消／额度不足 → saved + preparation.incomplete。后段额度恢复时沿原输入续办，仍能读到前段真实回执，且不重复写进展。撤销后的历史回执不能继续表示当前有效保存。

调用链已核对：HTTP 路由原样转交 `coreInbox.receipt`；助手保存完成回调也使用该方法；现有页面未根据这个同事回执直接展示成功提示。无需改 UI；保留原输入列表与第三方消息预览审核方式。同事输入不具备本人指令权，本轮没有自动向同事反馈或扩大外发权限。
