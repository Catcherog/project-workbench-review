# R1 UI 接口接续

沿用现有导航、项目排序、事项详情和助手。下面的语义已接入原入口；不是要求UI新增同名表单。例子均为合成数据。

## 输入和真实回执

继续使用 `POST /api/v2/codex/jobs` 及原同源令牌、会话、请求身份。图片先经原 `/api/v2/attachments` 保存，再按顺序提供 `attachmentIds`。事项内使用 sources 上下文和原 p1Input；全局使用 workspace/projects 上下文，后台逐事项调用同一 P1 时间、保存和权限路径。

```json
{
  "workspaceId": "synthetic",
  "requestId": "stable-input-1",
  "sessionId": "session-1",
  "parentJobId": "",
  "mode": "answer",
  "contextRef": {"kind": "sources", "id": "item-report"},
  "text": "已联系责任人，周三检查",
  "sourceIds": [],
  "attachmentIds": ["original-image-1", "original-image-2"],
  "p1Input": {
    "occurredAt": "2026-10-13T09:00:00+08:00",
    "expectedVersion": 3,
    "expectedBasis": "current-item-basis",
    "expectedEvidenceBasis": "current-evidence-basis",
    "manual": {}
  }
}
```

未知POST先查询 `GET /api/v2/codex/requests/{requestId}?workspaceId=...`。p1Outcome 兼容原保存/讨论/待澄清交互；coreOutcome 提供实际受影响事项、未完成决定、原输入、重复原图说明和整次撤销身份。保存状态来自持久回执，不能从回答文字推断。失败保留草稿，已保存而刷新失败单独反馈。

复杂请求还返回 coreWorkOutcome：running、prepared、partial、incomplete。第一段已保存而第二段仍运行时，页面明确显示“本地记录已保存，正在核对相关依赖与协作准备”。后段取消或失败不能显示为“没有写入”，也不能将整个请求当作全部完成。

## 原事项操作

仍调用 `/api/v2/work-items`，保留 expectedVersion、expectedBasis、expectedEvidenceBasis 和 requestId。

| action | 参数 | 可观察结果 |
|---|---|---|
| core-admit | 当前版本和依据 | 候选纳入，不批准消息或建外部Tasks |
| core-priority | priority；P0可附明确fullFocus | 记录人工基准等级；旧临时等级不覆盖新决定 |
| core-pause | 可选until或manualResume | 暂停常规提醒；未指定时按实际日历算下一工作日9:00 |
| core-resume | 无额外日期 | 先核对最新，再恢复；清零但保留同轮升级机会 |
| core-weekly | time，可选1—7的weekday | P3周度安排；省略星期表示最后实际工作日 |
| p1-undo | 原operationId | 全部相关冲突检查后撤销，原件和已发事实保留 |

候选、待审核和已结束仍在原入口可达。原“接手处理”不代表接管整件事项全部自动操作；具体执行权见消息接口。

## 推进投影与日历

`GET /api/v2/core?workspaceId=...&sourceId=...` 返回同一事项的core、有效等级、时间、提醒资格、消息批次、本人通知回执、待关联输入、可用人员与群范围。省略事项ID供全局助手集中显示。

首先展示当前需要、责任步骤、有效安排和下一步，然后展开来源、依赖和历史。notice.eligible=false可能表示有效等待、已结束、暂停、日历缺口或尚未到时，不能统一叫“完成”。

`POST /api/v2/core` 的 configure 保存有来源、版本、起止和逐日布尔值的日历，以及工作区持续跟进开关。revision冲突返回409。日历缺口不改变业务期限。设置入口位于原“设置与备份”。

## 资料与协作接口

以下action均提交到 `/api/v2/core`：

| action | 输入及可观察结果 |
|---|---|
| dependency | 事项版本、真实依赖和原文proof；保存影响、缺口和候选方案，不改计划或调人 |
| delivery | 实际交付物/节点、要求与proof；返回模板、材料和待预览消息，实际审核和关联由业务对象读取 |
| resolve-recipient | 已知人员ID及完整姓名/邮箱；当前账号唯一匹配后保存身份，否则给具体缺口 |
| prepare-messages | 逐条事项、收件人、完整正文、proof和requestId；只生成预览 |
| decide-messages | 消息ID、预览指纹及edit/cancel/approve；可另列独立admissions，部分批准 |
| execute-messages | 批次ID；仅执行当前仍有效、已批准且执行权为AI的消息 |
| message-authority | 消息ID、预览指纹、takeover/release；只改变该操作执行及重试权 |
| reconcile-messages | 批次ID；查询原发送，未知不当未发出 |
| reconcile-notice | 本人通知来源ID；查询真实回执，电脑排队不计有效提醒 |
| associate-input | 待关联输入ID、原版本、明确目标事项ID；处理原件，不重建事项 |
| input-receipt | 输入来源ID；核对本人回复回执，与业务保存状态分开 |

消息状态有pending_review、approved、sending、sent、readback_verified、failed_not_sent、unknown、needs_preview、blocked、stopped、cancelled。旧批准保留完整内容；对象或正文变化后不可沿用。发送、可见、已读、知晓、认可和业务完成不能混为一谈。

409表示版本、依据、账号或批准范围变化；422表示内容、日期、引用或关系不成立；429表示调用预算或并发限制。均保留原输入，先查原结果，不用新请求ID盲目重发。恢复副本保留历史，不自动启用旧调度或交回人工接手的动作。
