# R10-FIX1 SFT 首批方案

用户已授权修复后开展 SFT。拟先采用32条训练、8条开发数据，按16/4个家族隔离；单次遍历。原2400条模板候选不全部灌入首轮。

这些样本均为合成、执行助手审阅，真人逐条批准数为0。另冻结14个新合成组合测试，未纳入训练；其不是独立工程师业务留出集。现有Mac MLX入口只允许人工gold，并要求绑定真人未调参声明；当前尚不满足。

## 待明确的实验口径

合成实验SFT需要独立、明确标记的实验数据入口。原gold门禁、事实与发送保护仍保留；实验结果不能记作独立业务验收或生产可用。

## 40条具体样本

### r10-fix1-progress-0000 / train

现在进展怎么样？

输入：{"project": "合成项目001", "reported": "样机已到", "test_started": false, "next_check": "2099-01-01"}

目标回答：合成项目001样机已到，测试还没开始。下一检查点是2099-01-01。建议届时核对测试进展。

### r10-fix1-progress-0001 / train

现在进展怎么样？

输入：{"project": "合成项目002", "reported": "样机已到", "test_started": false, "next_check": "2099-01-02"}

目标回答：合成项目002样机已到，测试还没开始。下一检查点是2099-01-02。建议届时核对测试进展。

### r10-fix1-conditional_purchase-0000 / train

整理采购安排。

输入：{"project": "合成项目001", "planned_quantity": 2, "condition": "样机测试无问题", "order_placed": false}

目标回答：合成项目001如果样机测试无问题，计划按2件下单。目前还未下单。

### r10-fix1-conditional_purchase-0001 / train

整理采购安排。

输入：{"project": "合成项目002", "planned_quantity": 3, "condition": "样机测试无问题", "order_placed": false}

目标回答：合成项目002如果样机测试无问题，计划按3件下单。目前还未下单。

### r10-fix1-supplier_date-0000 / dev

交期怎么回复？

输入：{"project": "合成项目001", "estimated_arrival_date": "2099-01-01", "supplier_confirmed": false}

目标回答：合成项目001目前预计2099-01-01到料。供应商还未确认。建议核对供应商的预计交期。

### r10-fix1-supplier_date-0001 / dev

交期怎么回复？

输入：{"project": "合成项目002", "estimated_arrival_date": "2099-01-02", "supplier_confirmed": false}

目标回答：合成项目002目前预计2099-01-02到料。供应商还未确认。建议核对供应商的预计交期。

### r10-fix1-missing_owner-0000 / train

这件事谁负责？

输入：{"project": "合成项目001", "owner": null, "next_check": "2099-01-01"}

目标回答：合成项目001现有资料没有明确负责人。2099-01-01是下一检查点，现有资料未提供确认期限。建议核对负责人。

### r10-fix1-missing_owner-0001 / train

这件事谁负责？

输入：{"project": "合成项目002", "owner": null, "next_check": "2099-01-02"}

目标回答：合成项目002现有资料没有明确负责人。2099-01-02是下一检查点，现有资料未提供确认期限。建议核对负责人。

### r10-fix1-review_pending-0000 / train

这个交付物算完成了吗？

输入：{"project": "合成项目001", "submitted": true, "reviewed": false, "count": 2}

目标回答：合成项目001的2份材料已提交，审核还未完成。暂不能按验收完成记录。

### r10-fix1-review_pending-0001 / train

这个交付物算完成了吗？

输入：{"project": "合成项目002", "submitted": true, "reviewed": false, "count": 3}

目标回答：合成项目002的3份材料已提交，审核还未完成。暂不能按验收完成记录。

### r10-fix1-project_summary-0000 / train

说一下计划、进展、卡点和下一步。

输入：{"project": "合成项目001", "planned_test_completion_date": "2099-01-01", "progress": "样机已到", "blocker": "台架未排定"}

目标回答：合成项目001计划2099-01-01完成测试，目前样机已到。卡在台架尚未排定。建议确认台架档期及对计划的影响。

### r10-fix1-project_summary-0001 / train

说一下计划、进展、卡点和下一步。

输入：{"project": "合成项目002", "planned_test_completion_date": "2099-01-02", "progress": "样机已到", "blocker": "台架未排定"}

目标回答：合成项目002计划2099-01-02完成测试，目前样机已到。卡在台架尚未排定。建议确认台架档期及对计划的影响。

### r10-fix1-followup_preview-0000 / train

准备一条跟进消息。

输入：{"project": "合成项目001", "target": "同事甲", "quantity": 2, "response_deadline": "2099-01-01", "approved": false, "item_type": null, "followup_topic": null}

目标回答：拟跟进合成项目001，对象是同事甲，涉及2件，反馈期限为2099-01-01。物料类型和跟进主题缺失，正文尚未批准。建议补充物料类型和需要跟进的主题。

### r10-fix1-followup_preview-0001 / train

准备一条跟进消息。

输入：{"project": "合成项目002", "target": "同事甲", "quantity": 3, "response_deadline": "2099-01-02", "approved": false, "item_type": "试制件", "followup_topic": "回样时间"}

目标回答：拟发给同事甲：合成项目002这3件试制件的回样时间确认了吗？请在2099-01-02前同步一下。正文待你确认后发送。

### r10-fix1-pause-0000 / train

这个事项怎么处理？

输入：{"project": "合成项目001", "decision": "暂停", "next_check": "2099-01-01", "completed": false}

目标回答：合成项目001当前决定为暂停，下一检查点为2099-01-01。事项还未完成。

### r10-fix1-pause-0001 / train

这个事项怎么处理？

输入：{"project": "合成项目002", "decision": "暂停", "next_check": "2099-01-02", "completed": false}

目标回答：合成项目002当前决定为暂停，下一检查点为2099-01-02。事项还未完成。

### r10-fix1-resume-0000 / train

可以说恢复测试了吗？

输入：{"project": "合成项目001", "status": "待恢复", "planned_date": null, "estimate": 2, "estimate_unit": "点"}

目标回答：合成项目001保留2点估分，目前仍为待恢复。恢复时间未定，不能说已恢复测试。

### r10-fix1-resume-0001 / train

可以说恢复测试了吗？

输入：{"project": "合成项目002", "status": "待恢复", "planned_date": null, "estimate": 3, "estimate_unit": "点"}

目标回答：合成项目002保留3点估分，目前仍为待恢复。恢复时间未定，不能说已恢复测试。

### r10-fix1-unknown_send-0000 / train

上一条消息发出去了吗？

输入：{"project": "合成项目001", "delivery": "unknown", "message_id": null}

目标回答：合成项目001这条消息的发送结果还不明确，尚未取得消息回执。建议先核对原请求，避免重复发送。

### r10-fix1-unknown_send-0001 / train

上一条消息发出去了吗？

输入：{"project": "合成项目002", "delivery": "unknown", "message_id": null}

目标回答：合成项目002这条消息的发送结果还不明确，尚未取得消息回执。建议先核对原请求，避免重复发送。

### r10-fix1-node_vs_task-0000 / train

子任务完成就代表节点完成吗？

输入：{"project": "合成项目001", "finished_subtasks": 1, "all_subtasks": 2, "node": "进行中"}

目标回答：合成项目001的2项子任务中有1项已标记完成，节点仍为进行中。不能写成整个节点已完成。

### r10-fix1-node_vs_task-0001 / train

子任务完成就代表节点完成吗？

输入：{"project": "合成项目002", "finished_subtasks": 2, "all_subtasks": 3, "node": "进行中"}

目标回答：合成项目002的3项子任务中有2项已标记完成，节点仍为进行中。不能写成整个节点已完成。

### r10-fix1-estimate_unit-0000 / train

这些估分是多少人天？

输入：{"project": "合成项目001", "estimate": 2, "unit": null}

目标回答：合成项目001记录的估分数值为2。没有注明工时单位，暂不能换算成人天。

### r10-fix1-estimate_unit-0001 / train

这些估分是多少人天？

输入：{"project": "合成项目002", "estimate": 3, "unit": null}

目标回答：合成项目002记录的估分数值为3。没有注明工时单位，暂不能换算成人天。

### r10-fix1-partial_done-0000 / dev

这批任务是否都结束了？

输入：{"project": "合成项目001", "total": 2, "done": 1, "remaining": 1}

目标回答：合成项目001共2项，已完成1项，还剩1项未完成。不能按全部结束记录。

### r10-fix1-partial_done-0001 / dev

这批任务是否都结束了？

输入：{"project": "合成项目002", "total": 3, "done": 2, "remaining": 1}

目标回答：合成项目002共3项，已完成2项，还剩1项未完成。不能按全部结束记录。

### r10-fix1-conflict-0000 / train

两个进度反馈不一致怎么办？

输入：{"project": "合成项目001", "report_a": "已完成", "report_b": "仍在测试", "accepted_evidence": null}

目标回答：合成项目001一份反馈说已完成，另一份说仍在测试。当前没有验收依据，结论待核。建议核实两份反馈的差异。

### r10-fix1-conflict-0001 / train

两个进度反馈不一致怎么办？

输入：{"project": "合成项目002", "report_a": "已完成", "report_b": "仍在测试", "accepted_evidence": null}

目标回答：合成项目002一份反馈说已完成，另一份说仍在测试。当前没有验收依据，结论待核。建议核实两份反馈的差异。

### r10-fix1-material_gap-0000 / train

先给我一份草稿。

输入：{"project": "合成项目001", "known_quantity": 2, "approval": null, "responsible_person": null}

目标回答：合成项目001草稿：已知数量为2件。批准状态和负责人缺少依据，标为待补。

### r10-fix1-material_gap-0001 / train

先给我一份草稿。

输入：{"project": "合成项目002", "known_quantity": 3, "approval": null, "responsible_person": null}

目标回答：合成项目002草稿：已知数量为3件。批准状态和负责人缺少依据，标为待补。

### r10-fix1-meeting_invite-0000 / train

拟一句会议邀请。

输入：{"project": "合成项目001", "meeting_topic": "问题确认", "time": "2099-01-01 10:00–11:00", "sent": false}

目标回答：邀请草稿：合成项目001的问题确认会议拟于2099-01-01 10:00–11:00，方便参加吗。还未发送。

### r10-fix1-meeting_invite-0001 / train

拟一句会议邀请。

输入：{"project": "合成项目002", "meeting_topic": "问题确认", "time": "2099-01-02 10:00–11:00", "sent": false}

目标回答：邀请草稿：合成项目002的问题确认会议拟于2099-01-02 10:00–11:00，方便参加吗。还未发送。

### r10-fix1-report_summary-0000 / train

这周进度怎么概括？

输入：{"project": "合成项目001", "submitted": 2, "reviewed": 1, "next_check": "2099-01-01"}

目标回答：合成项目001本周提交2份材料，其中1份已审核，剩余1份未审核。下一检查点是2099-01-01。

### r10-fix1-report_summary-0001 / train

这周进度怎么概括？

输入：{"project": "合成项目002", "submitted": 3, "reviewed": 2, "next_check": "2099-01-02"}

目标回答：合成项目002本周提交3份材料，其中2份已审核，剩余1份未审核。下一检查点是2099-01-02。

### r10-fix1-outside_item-0000 / dev

这条应该放到哪个项目？

输入：{"topic": "合成项目001模板协调", "explicit_outside": true, "linked_project": null}

目标回答：合成项目001模板协调已明确为项目外事项，当前没有关联项目。建议按原主题继续跟进。

### r10-fix1-outside_item-0001 / dev

这条应该放到哪个项目？

输入：{"topic": "合成项目002模板协调", "explicit_outside": true, "linked_project": null}

目标回答：合成项目002模板协调已明确为项目外事项，当前没有关联项目。建议按原主题继续跟进。

### r10-fix1-scope_missing-0000 / train

能直接采用这个结论吗？

输入：{"project": "合成项目001", "reported_scope": "首轮样机", "mass_production_verified": false}

目标回答：合成项目001现有结论只覆盖首轮样机。尚未验证量产适用性，不能直接扩展到量产。

### r10-fix1-scope_missing-0001 / train

能直接采用这个结论吗？

输入：{"project": "合成项目002", "reported_scope": "首轮样机", "mass_production_verified": false}

目标回答：合成项目002现有结论只覆盖首轮样机。尚未验证量产适用性，不能直接扩展到量产。

### r10-fix1-late_feedback-0000 / dev

检查点到了但没反馈，怎么写？

输入：{"project": "合成项目001", "as_of_date": "2099-01-01", "new_feedback": null, "next_check": "2099-01-08"}

目标回答：合成项目001截至2099-01-01还没有收到新反馈，不能据此判定已完成。下一检查点为2099-01-08。建议核实当前进度。

### r10-fix1-late_feedback-0001 / dev

检查点到了但没反馈，怎么写？

输入：{"project": "合成项目002", "as_of_date": "2099-01-02", "new_feedback": null, "next_check": "2099-01-09"}

目标回答：合成项目002截至2099-01-02还没有收到新反馈，不能据此判定已完成。下一检查点为2099-01-09。建议核实当前进度。
