from pathlib import Path
import json,csv,math,statistics,hashlib
R=Path(__file__).resolve().parents[3];T=Path(__file__).resolve().parents[1]
run=R/'AM-HARNESS-20261031-01/R7/private/r10-synthetic-run-001';plan=run.with_name(run.name+'-plan')
read=lambda p:json.loads(p.read_text())
cfg=read(plan/'config.json');steps=read(run/'steps.json') if (run/'steps.json').exists() else []
fit=read(run/'fit.json') if (run/'fit.json').exists() else {};reload=read(run/'reload.json') if (run/'reload.json').exists() else {}
metrics={'run':str(run),'steps':steps,'fit_complete':fit.get('training_completed',False),'reload_verified':reload.get('fresh_load_verified',False),'dev':None}
def dev_stats(name):
 vals=[v for v in read(run/name).values() if v['split']=='dev'];n=sum(len(v['target_logprobs']) for v in vals)
 loss=-sum(sum(v['target_logprobs']) for v in vals)/n
 return {'examples':len(vals),'completion_tokens':n,'token_weighted_cross_entropy':loss,'perplexity':math.exp(loss)}
if (run/'teacher-base.json').exists() and (run/'teacher-sft.json').exists():metrics['dev']={'before':dev_stats('teacher-base.json'),'after':dev_stats('teacher-sft.json')}
(T/'evidence/training-metrics.json').write_text(json.dumps(metrics,ensure_ascii=False,indent=2))
with (T/'evidence/training_steps.csv').open('w') as f:
 w=csv.writer(f);w.writerow(['step','loss','completion_tokens','gradient_l2','clip_scale','parameter_delta_l2','elapsed_seconds','sample_ids'])
 for s in steps:w.writerow([s['optimizer_step'],s['loss'],s['completion_tokens'],s['gradient']['l2_norm'],s['gradient_clip_scale'],s['parameter_delta']['l2_norm'],s['elapsed_training_seconds'],';'.join(s['ids'])])
with (T/'evidence/per_example_losses.csv').open('w') as f:
 w=csv.writer(f);w.writerow(['step','sample_id','completion_tokens','mean_token_cross_entropy','batch_token_weight'])
 for s in steps:
  for x in s['per_example_losses']:w.writerow([s['optimizer_step'],x['id'],x['completion_tokens'],x['mean_token_cross_entropy'],x['completion_tokens']/s['completion_tokens']])
parts=[r'''# R10-FIX1 合成实验 SFT：loss、样本与实测数据

本轮用户已明确批准合成实验SFT。数据仍标记为合成、非逐条人工gold；独立业务验收延期。此处只展示本轮实测，不混用R8的旧loss。

## 实际 loss 函数

对第 i 条样本，只在助理回答及聊天模板收尾 token 的位置计算下一 token 交叉熵。输入提示位置在 labels 中为 -100，实际计算时只提取回答位置的 logits；输入仍参与条件概率，但不作为监督目标。包括结束符，以及实际模板保留的尾随空白 token。

\[
L_i(\theta)=-\frac{1}{T_i}\sum_{t\in C_i}\log p_\theta(y_{i,t}\mid x_i,y_{i,<t})
\]

每4条样本累积一次梯度，按回答 token 数加权：

\[
L_B(\theta)=\sum_{i\in B}\frac{T_i}{\sum_{j\in B}T_j}L_i(\theta)
\]

自然对数，单位为 nats/token。没有加入DPO、KL或强化学习损失。AdamW的weight decay是独立的参数衰减，不是写进交叉熵里的L2损失项。

对应执行逻辑：

```python
logits = completion_position_logits(model, row).astype(float32)
targets = input_ids[loss_positions + 1]
loss_i = cross_entropy(logits, targets, reduction="mean")
weight_i = completion_tokens_i / total_batch_completion_tokens
batch_loss = sum(weight_i * loss_i)
grads = sum(weight_i * grad(loss_i))
clip_scale = min(1.0, 1.0 / l2_norm(grads))
optimizer.update(model, grads * clip_scale)
```

上段是阅读用摘写；完整实际源码见训练器链接，原始数据与每步日志可独立核算。

## 训练配置

| 项目 | 本轮配置 |
|---|---|
| 基座 | 本机固定版本 Qwen 27B，MLX 4-bit；从基座新建adapter |
| 数据 | 32条train、8条dev，16/4个场景家族隔离 |
| 保留测试 | 另冻结14个合成组合任务，不进训练；非独立真人业务测试 |
| 遍历次数 | 1次，不重复样本凑步数 |
| 梯度累积 | 4条/更新，共计划8次更新 |
| 学习率 | 0.00001（1e-5），固定 |
| 优化器 | AdamW，β₁=0.9，β₂=0.999，ε=1e-8 |
| Weight decay | 0.01 |
| Bias correction | false，沿用本机已验证配置 |
| 梯度裁剪 | 全局L2范数上限1.0 |
| LoRA | 最后2层，rank=8、scale=2.0、dropout=0 |
| 可训练参数 | 预期713,472；运行时逐项校验实际参数集合 |
| 种子 | 221 |
| 序列上限 | 1024 token，超长拒绝，不截断 |
| 单工作进程限时 | 300秒；保存后必须独立新进程重载 |
| 资源 | 原协调器、原内存/业务让路检查及精确Q8恢复 |

## 当前实测
''']
parts += [f"已记录 **{len(steps)}/8 次参数更新**；训练完成：**{metrics['fit_complete']}**；独立重载验证：**{metrics['reload_verified']}**。"]
if steps:
 parts += ['| 步骤 | Loss | 回答token数 | 梯度L2（裁剪前） | 裁剪系数 | 本步参数变化L2 |','|---:|---:|---:|---:|---:|---:|']
 for s in steps:parts.append(f"| {s['optimizer_step']} | {s['loss']:.8f} | {s['completion_tokens']} | {s['gradient']['l2_norm']:.8f} | {s['gradient_clip_scale']:.6f} | {s['parameter_delta']['l2_norm']:.8f} |")
 parts += ['各步骤使用不同的4条样本，逐步loss不能当作同一测试集的下降曲线。更可比较的是下表同一8条dev的训练前后loss。']
if metrics['dev']:
 parts += ['| 固定开发集 | 交叉熵（nats/token） | Perplexity | 回答token总数 |','|---|---:|---:|---:|']
 for k,label in [('before','训练前基座'),('after','训练后adapter')]:
  v=metrics['dev'][k];parts.append(f"| {label} | {v['token_weighted_cross_entropy']:.8f} | {v['perplexity']:.6f} | {v['completion_tokens']} |")
 parts += ['开发集loss反映对这些目标答案的概率，不能单独证明事实正确率、自然表达质量或完整Agent任务完成率。']
if fit:
 parts += [f"实际可训练参数：{fit['trainable_parameters']:,}；完成训练样本：{fit['train_examples']}；完整参数变化L2：{fit['parameter_delta']['l2_norm']:.8f}；MLX训练峰值内存：{fit['peak_memory_bytes']/2**30:.3f} GiB。"]
parts += ['## 完整原件与样本',
 f"- [40条可读样本]({T/'01_SFT首批方案与样本.md'})\n- [实际train.jsonl]({plan/'train.jsonl'})\n- [实际dev.jsonl]({plan/'dev.jsonl'})\n- [完整参数config.json]({plan/'config.json'})\n- [逐步loss与梯度CSV]({T/'evidence/training_steps.csv'})\n- [逐条样本loss CSV]({T/'evidence/per_example_losses.csv'})\n- [原始steps.json]({run/'steps.json'})\n- [token、labels与loss位置]({run/'tokenized.json'})\n- [实际训练器]({R/'am-style-r3/training/mlx_synthetic_runtime.py'})",
 '本实验直接使用合成事实提示与正文回答训练；它不是生产AM末端表达封装的等价验证。新adapter未合并、未部署，生产Q8不切换。']
(T/'03_SFT训练细节与loss.md').write_text('\n\n'.join(parts)+'\n')
print(json.dumps({'steps':len(steps),'fit_complete':metrics['fit_complete'],'reload_verified':metrics['reload_verified'],'dev':metrics['dev']},ensure_ascii=False))
