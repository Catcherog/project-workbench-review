# R5 表达效果报告

模式：`fixture`；材料性质：`not_independent`。

| 组别 | 计划场景 | JSON通过 | 人工已评场景 | 人工可直接采用 | 自然度中位数 |
| --- | ---: | ---: | ---: | ---: | ---: |
| production_q8 | 3 | 2 | 0 | 0 | None |
| mlx_base | 3 | 3 | 0 | 0 | None |
| mlx_sft | 3 | 3 | 0 | 0 | None |

## 全部状态与延迟

未执行、失败、超时和未知均保留在计划分母。所有有观测的尝试时长包含失败等待；成功请求另列。延迟使用线性插值，单位毫秒。
真实运行中，production_q8 计入原队列等待至响应回读；MLX 的 end_to_end 只计单条生成，一次模型加载另列 model_load。它们都不等于完整业务任务耗时，也不直接跨运行时判断快慢。

| 组别 | 状态计数 | 尝试 n | 尝试 p50 / p95 / max | 完成 n | 完成 p50 / p95 / max | 无尝试时长的计划项 |
| --- | --- | ---: | --- | ---: | --- | ---: |
| production_q8 | completed: 2, missing: 1 | 2 | 100.50 / 100.95 / 101.00 | 2 | 100.50 / 100.95 / 101.00 | 1 |
| mlx_base | completed: 3 | 3 | 101.00 / 101.90 / 102.00 | 3 | 101.00 / 101.90 / 102.00 | 0 |
| mlx_sft | completed: 3 | 3 | 101.00 / 101.90 / 102.00 | 3 | 101.00 / 101.90 / 102.00 | 0 |

## 同基座比较

```json
{
  "completed_pairs": 3,
  "same_runner_source_pairs": 3,
  "human_rated_pairs": 0,
  "relative_vote_count": 0,
  "relative_case_count": 0,
  "relative_votes": {},
  "eligible_preference_evidence": 0,
  "source_mismatch_case_ids": [],
  "paired_case_ids": [
    "R5-CAL-r5-owner-stage-limit-1",
    "R5-CAL-r5-owner-stage-limit-2",
    "R5-CAL-r5-owner-stage-limit-3"
  ]
}
```

## 结论边界

自动报告不批准生产启用，不将JSON、有限语义校验或NLL当作自然度改善。
生产Q8单独作为参照；MLX base与SFT的同输入配对结果用于评估adapter效果。

No independence-assuming interval: cases may share scenario groups; report group counts and paired coverage. Small exposed samples cannot establish naturalness improvement.
