/** Shared wording contract. Business classification and execution stay in their existing flows. */
export const summaryFieldInstructions=`摘要按“发生了什么、有什么影响、需要你做什么、依据与缺口”四个问题组织，面向项目经理，不写系统处理说明。
title写具体事项和当前状态，不能用“采集整理”、群名加时间戳代替事情。summary回答谁在何时、围绕什么事、说了什么或有什么新变化；只写实际已读到的事实，人名或时间未提供就省略，不能把采集时间当事件时间。impact说明对进展、期限或原事项的具体影响；未能判断就明确说“目前无法判断”及原因，不把未知说成无影响。
nextStep必须给出明确建议：需要谁做什么、核对哪个问题或形成什么结果；有原文期限才写期限。无需本人办理时写“当前无需你办理”并说明原因。缺资料时说清先补读什么、补读后判断什么；只允许建议，不能宣称已补读、已安排或会自动执行。禁用“由本人选择处置方式”“请自行判断”“持续关注”“待核实”作为完整下一步。
limitations/uncertainties列出真正缺失或冲突的内容及其对判断的限制；没有缺口可留空。只收到链接时先说是谁分享了什么链接，再说明正文未读、影响未知、建议先补读确认是否有办理要求；不能凭群名猜文档标题或业务事实。资料读取缺口本身不自动升级成业务风险或强制待办。人工判断、已办结和忽略状态沿用原规则。`;

export const intakeSummaryInstructions=`${summaryFieldInstructions}
本接口没有独立impact/nextStep/limitations字段，因此顶层summary和每份documents.summary都用以下四行纯文本（保留换行与中文冒号，不用Markdown）：
发生了什么：具体事实
有什么影响：已知影响，或无法判断的原因
需要你做什么：具体建议，或无需办理及理由
依据与缺口：消息/正文实际读取情况及缺失内容
顶层summary不超过600字，每份documents.summary不超过500字；每段1至2句。不逐条罗列“未更新哪些系统字段”。多事项分句交代，不凭格式编造动作。`;
