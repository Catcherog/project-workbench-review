# DPO 代码设计与下一次实现边界

## 本包实际具备什么

保留 R3 的 CUDA/TRL `training/train_dpo.py`、数据校验与固定 SFT reference 逻辑；新增的是完整的 Qwen wire/人工偏好回读与 MLX SFT 机制验证。**没有新增已验证的 MLX DPO 后端，没有执行 DPO，没有偏好训练结果。**

当前原机路线为 MLX，不能将 MLX adapter 的文件名改成 PEFT 文件名后交给 TRL。应先选择后端并验证权重键、缩放定义、tokenizer、chat template、量化与前向结果的一致性。资源环境或格式未解决时，应保留精确阻塞原因。

## 一、数据合同

一个 style DPO 记录包含：

- 一个明确 student wire prompt；producer/judge 的输入单独记录。
- 两条不同的完整 JSON text 答复，共用同一事实、frame、policy、目标 prompt。
- 双方事实正确；chosen 还必须明确自然、可直接采用。
- 人类对该对答复的真实相对偏好、时间、reviewer、context与候选SHA。
- 固定 scenario_group 和 train/dev split，避免实体改名后泄漏。

同一情境的两个不同模型身份不自动构成偏好。两条分别被认可的示范若 prompt 不同，也不是一个 DPO 对。unknown/缺失/Codex blocked 不能充当负例。含事实错误的反例归入语义测试；若以后要训练事实纠错，应设另一 objective 与评审合同，不能悄悄混入本轮风格偏好。

## 二、固定参考与损失

选择经过机制复核的 SFT checkpoint S。它可来自 R4 pilot；不存在永久锁定 R3 单步产物的要求，但所选 hash 必须明确。

policy 初始化为 S；reference 是冻结的 S。使用 completion-only 的序列 log probability，prompt 不计损失，EOS/EOM 与 SFT 保持一致；不截断或丢一侧答案。定义：

```python
policy_margin = logp_policy(chosen | prompt) - logp_policy(rejected | prompt)
reference_margin = logp_reference(chosen | prompt) - logp_reference(rejected | prompt)
loss = -log_sigmoid(beta * (policy_margin - reference_margin))
```

这描述标准 sigmoid DPO 的计算设计，尚未在当前 MLX 实现。算法来源：[DPO 原论文](https://arxiv.org/html/2305.18290v3)。beta、优化器、步数和长度策略应在新实验 manifest 中预先固定，不能根据封存测试调参。默认采用序列 logprob 求和；若改变为长度归一化，应改 objective 版本并单独评估，不能仍声称同一实验。

最重要的验证点不是 loss 降低，而是 reference 始终不变。每个参考缓存必须绑定 SFT/base/tokenizer/template/backend/code、实际 token IDs、chosen/rejected SHA；任何不匹配都重新计算，不退回原base。

## 三、内存受限的 MLX 路线建议

这是待实现设计，不能拿作已运行代码：

1. 独立 reference worker 只加载所选 S，按冻结输入计算两侧 logprob，保存绑定缓存；确认退出和释放内存。
2. 独立 policy worker 从相同 S 加载可训练 adapter，用缓存 reference 完成小步更新；训练前后重复保存精确参数证据。
3. 独立 reload worker 核对 saved adapter 全部键、逐张量值与 teacher概率，保持原资源/租约/停止条件。
4. 同输入对照固定 S 与 DPO checkpoint，先判事实，再做人类自然度偏好；不以训练中 chosen胜率代替外部效果。

预计算 reference 可以避免两个27B模型同时驻留，但不能省掉对缓存来源和数值的一致性证明。若该 MLX API 的 value_and_grad/模型结构不能可靠实现，则转向独立 CUDA资源并先做可审计转换；本轮不自动申请硬件、安装依赖或开始另一平台训练。

## 四、最小实验顺序

先用一条真实、同prompt、双方事实正确的偏好对做 mechanics，仅证明 loss、mask、梯度和固定reference。没有这条偏好时停止；不能借用助手意见造标签。

下一轮 pilot 建议先准备16–32条train、至少8条dev，分属至少8/4个场景组，一遍数据，有限步数。数量属于待落实的项目小试设计，不是统计功效保证；正式配置应在具体资源与数据齐备后冻结。当前本包的MLX可执行入口只支持SFT mechanics/pilot，不会误启动该DPO计划。

首轮重点诊断：回答是否越来越短而漏事实、是否过多套话、是否把未执行说成已执行、是否在未知时强行给结论、是否只拟合8个已展示场景。成对 log-ratio 只是训练诊断，不等于全分布 KL。

## 五、验收输出

DPO 完成时至少提供参考缓存身份、参考权重不变证据、policy真实梯度/参数变化、保存与新进程重载、冻结独立场景的双臂答复与人类反馈。分别报告事实失败、unknown、采用率、可比较对数和偏好；没有改善或出现退化也如实保留。

没有这些证据时，正确状态是“未执行/机制未闭合/尚无改善证据”中的相应一项，不能把模型训练进程退出0提升成表达验收通过。
