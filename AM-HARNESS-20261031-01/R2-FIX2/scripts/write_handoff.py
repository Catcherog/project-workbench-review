from pathlib import Path
import json,subprocess
T=Path(__file__).resolve().parents[1]
sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=T/'worktree',text=True).strip()
summary=json.loads((T/'evidence/model-summary.json').read_text());first,final=summary['batches']
runtime=json.loads((T/'evidence/runtime-final.json').read_text())
assert runtime['source_commit']==sha and final['record_count']==12 and first['record_count']==18
def write(name,text):(T/name).write_text(text)
write('00_当前交接.md',f'''# AM-HARNESS-20261031-01 / R2-FIX2 当前交接

要求：v2.0-design.1、R2-FIX1 已确认要求及本次独立复审。日期：2026.11.2（Asia/Shanghai）。

**四项限定补修已实施待审计；整体启用与业务验收未通过。** 原服务已加载最终源码，新表达与目标跟踪继续关闭。

| 版本 | 固定依据 |
| --- | --- |
| 源码基线 | `f767cea93444217d40a52bea6330f51434f3ce27` |
| 审核基线 | `ee1e023e117752e2625d2cb7ee26541f9d859925` |
| 本轮首批模型源码 | `bbba6341e4f248702071be23bbe887aced1b02fb` |
| 本轮最终源码 / 补充模型源码 | `{sha}` |
| 本轮审核 SHA | 本文件所在远端固定提交；由最终审核链接与独立远端读回记录标识，不能用源码 SHA 代替 |

本轮从原工作树增量实施，初始已跟踪差异为空，原未跟踪资料保留；未用审核副本覆盖原配置或数据库。[本轮指令及采用范围](input/01_本轮指令与采用范围.md)、[独立复审原文](input/独立复审原文.md)、[保留证明](evidence/preservation-proof.json)。

## 已实施

- F01：稳定目标、原调用与原生创建回执绑定；相似的两条事项各自创建；缓存不换参数重包装；同一原生回执不满足两个独立创建目标。
- F02：executing/unknown 按目标及原提交阻断；create_followup 从原操作记录只读对账后恢复；空白或等价改述不再次创建。原已知失败及外部批准/对账规则保留。
- F03：宿主冻结必答与允许省略集合；真实语义陈述才能覆盖事实，追问/建议不能冒充事实覆盖。
- F04：预测、建议、否定、时间、范围及业务状态成为显式约束；支持限定的负责人/进展关系。仅添加来源前缀仍是原文投影。

## 验证

44 项本轮新增检查及原 74 项通过，均已包含于完整原工程 **798 通过、27 既有失败，退出码 1**。27 项名称、状态、错误和断言位置与基线一致。Harness 130、会话 193 通过；会话 verify/pytest 和脱敏重建为同组复跑，不重复累计。脱敏复跑同为 798/27；24 项错误正文仅派生项目 UUID 因命名空间脱敏变化，已给出精确映射，未声称原文完全一致。

新增真实 Qwen 两批共 **30 条观察**，按两个源码版本分别保留。首批 18 条中正常表达 1/4 被隔离管线选为自由候选，后续有限语法补修未改写旧成绩；最终批 12 条中 4/4 正常表达被隔离管线选为自由候选，6/6 指定错误提案被拒绝。表达专测没有实际业务投递。主循环中的创建/续接限定核对通过，混合查询仍待提醒时间；主循环没有自由提案采用，不能据此称整体新表达验收通过。[验证与模型评估](02_验证与模型评估.md)。

原 288 条、每模式 123 资格分母和首轮 48 项盲评保持原样，296 份相关本地证据指纹一致。本轮不改 QRY01 的旧资格定义，不合并新旧分母。

## 运行

实际加载 **174 份文件**与最终源码指纹一致；原 Qwen `qwen3.8:27b-bartowski-q8_0`、原协调器、唯一消费者、600 秒身份与 `ledger_write=false` 保持。response=`legacy`，旧重写=`off`，goal_tracking=`false`。原桥接仅维护一次，Qwen/Ollama 未重启或替换，配置字节保持，原连接与模型通道空闲已独立核对。[运行状态](evidence/runtime-final.json)、[加载映射](evidence/runtime-loaded-map.json)。

首次维护检查被 667 个上轮过期只读验证标记阻挡。已在持有原模型租约、确认协调器 complete/无暂停及业务空闲后，仅对超过 24 小时的这些标记作本次维护判定例外；所有原文件和未知结果不动、不重放。本轮模型结果均在，安装后再次核对旧标记字节未变。详见 [维护说明](04_复现与运行.md)。

## 审核材料

1. [修复与边界](01_修复与证据边界.md)、[最终差异](FINAL.diff)、[测量后增量](MEASURED_TO_FINAL.diff)。
2. [四项反例与检查](evidence/four-findings-tests.json)、[基线反例](evidence/baseline-final/counterexamples.txt)、[27 项逐项比较](evidence/regression-comparison.json)。
3. [模型汇总](evidence/model-summary.json)、[首批冻结输入](input/model-batch.json)、[最终批冻结输入](input/model-supplement.json)。
4. [未完成边界](03_未完成与验收边界.md)、[复现与运行](04_复现与运行.md)、[验收状态](05_验收状态.md)。
5. [源码指纹](SOURCE_SHA256.json)、[首批源码指纹](MEASURED_SOURCE_SHA256.json)、[交付清单](MANIFEST.json)。

仅发布本轮 R2-FIX2 目录；固定远端提交逐文件字节/指纹/模式回读后提供审核链接。原通用目标、专业异步流程、精确依赖、人工自然度、手机、独立人员及正式业务验收边界继续保留。
''')
rows=[]
for batch in (first,final):
    e=batch['expression'];a=batch['full_loop']['legacy'];b=batch['full_loop']['enforce']
    rows.append(f"| {batch['batch']} | `{batch['source_commit'][:8]}` | {batch['record_count']} | {e['normal_free_selected']}/{e['normal_observed']} | {e['adversarial_observed']-e['adversarial_accepted']}/{e['adversarial_observed']} | {batch['model_calls']} |")
write('02_验证与模型评估.md','''# 验证与模型评估

## 工程检查与反例

基线从 f767cea9 的独立 git archive 运行最终反例工装：8 项失败、1 项正常用例通过，真实退出码 1。两种 F02 变体均直接核对到重复落库（2 != 1）；F01 两种完成绑定反例、F03 两种事实遗漏及 F04 错误放行/正常受阻均复现。

最终源码中，本轮新增 44 项全部通过；原 74 项保留并通过。完整原工程 798 通过、27 既有失败、退出码 1；Harness 130、会话 193 通过。27 项逐项名称、状态、错误和断言位置完全一致。脱敏重建复跑同组结果；其 24 项错误正文只包含已证明的命名空间脱敏导致的 UUID 改变，名称、状态、类型及断言位置不变。原始日志、真实退出码、精确映射与早期工装失误说明均保留。

## 新增真实模型批次

每批执行前冻结输入、目的、期待行为、源码和工装指纹。旧 QRY01、288 条主测及 123 分母不变。本轮为定向风险观察，不重做旧主测资格评分。

| 批次 | 源码 | 观察数 | 正常表达的隔离自由选择 | 指定错误提案拒绝 | 实际模型调用数 |
| --- | --- | ---: | ---: | ---: | ---: |
'''+ '\n'.join(rows)+f'''

正常表达和指定错误提案在测量前分组：每批 4 个正常表达、6 个对抗输入。最终 4 个正常输入覆盖“事实＋追问”、预测、负责人及进展；6 个错误输入覆盖引用冒充覆盖、任意省略、丢预测、换项目、扩大范围和改变否定。不是将 10/10 期待行为正确写成 10/10 自由采用。

首批 3 个正常提案被拒的原始结果保留。随后只扩充完整主体/谓词/值的连接语法、绑定每条事实自己的限定，并修正来源前缀的投影计数；新 profile 为 bounded-zh/3.1。最终批由 Qwen 重新生成，未给旧提案补新 hash。首批未受影响的 F01/F02 六条主循环观察继续按原版本复用，不能标为最终源码重跑。

## 各指标分开

| 指标 | 实际结果和解释 |
| --- | --- |
| 业务完成 | F01 两种模式分别创建两个原生事项；F02 普通继续/等价改述四条观察只保留原事项并核对原操作记录。混合查询两批均尚缺提醒时间，持久目标 blocked，响应管线 awaiting_input；没有建立提醒，不算完整业务完成 |
| 事实覆盖 | 最终 4 个正常表达均有校验通过的陈述覆盖必要事实；两种只追问的提案均不通过。主循环未生成提案时不计为语义覆盖成功 |
| 自由采用 | 最终表达专测隔离管线选择 4/4 正常自由候选；没有实际业务/平台投递。主循环全部 10 条观察自由采用数为 0；业务回执、保护块和回退均不计自由成功 |
| 投递 | 主循环首批 8/8、最终批 2/2 合成平台回读成功；真实飞书业务发送 0 |
| 时延 | 首批 4 对任务 legacy p95 {first['full_loop']['legacy']['task_seconds_p95']:.2f}s、enforce {first['full_loop']['enforce']['task_seconds_p95']:.2f}s；最终仅 1 对混合查询，legacy {final['full_loop']['legacy']['task_seconds_p95']:.2f}s、enforce {final['full_loop']['enforce']['task_seconds_p95']:.2f}s，不足以估计总体 p95，且新模式更慢 |
| 自然度 | 未人工评分；旧 48 项首轮盲评及缺失配对保留，不据本轮校验推断自然度通过 |

表达专测真实模型时延最终 p50 {final['expression']['seconds_p50']:.2f}s、p95 {final['expression']['seconds_p95']:.2f}s。样本很小，输入含指定反例，不构成生产自然度或时延验收。旧主测 p95 增加 39.3% 与自由采用 0/123 的成绩继续保留，不被这两批替代。

模型测试运行器的退出码 0 仅表示观察写出成功；原始结果中的 checks、采用、业务完成、投递和自然度各自单列。总计 30 条新增观察，不加入旧 288 条主分母；重建及重复检查不重复累计。
''')
write('05_验收状态.md',f'''# 验收状态

| 项目 | 状态 |
| --- | --- |
| 本轮四项限定补修及正反例 | 已实施；最终源码 `{sha}`，新增 44 项通过 |
| 原 74 项及受影响回归 | 通过；原断言文件字节保留 |
| 完整原工程 | 798 通过、27 既有失败、退出码 1；失败逐项一致 |
| 脱敏重建 | 同组复跑，原错误标识差异已精确解释，不重复累计 |
| 真实 Qwen | 首批 18 条、最终批 12 条；版本、分母与结果分列 |
| 原服务维护与读回 | 已完成；174 文件一致、唯一消费者与原模型保持 |
| 真实业务外发/新范围验证 | 本轮未执行；未扩大范围 |
| 生成路线整体启用 | 未通过；legacy / off / goal_tracking=false |
| 独立复审 | 待完成；本轮自测不能替代独立复审 |
| 人工自然度、手机、独立人员、正式业务 | 未完成；旧盲评未评分 |
| 通用目标、专业异步流程、精确依赖 | 保留原未完成边界 |
''')
print(json.dumps({'source':sha,'handoff':'00_当前交接.md','model_observations':30,'loaded_files':runtime['loaded_files']}))
