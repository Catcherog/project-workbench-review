# Codex 真实对照：继续保留门禁，补齐诊断证据

## 已有阻塞

[R3 固定 codex-preflight](https://github.com/Catcherog/project-workbench-review/blob/7d8a8a8dda4cc42f7dd6260c2f10adb1f6405757/AM-HARNESS-20261031-01/R3/evidence/codex-preflight.json)记载：CLI 0.163.0、配置 gpt-6-astra/max，已有禁用覆盖后仍能看到 functions.exec/wait 与 collaboration 工具。唯一 mock 调用没有真实模型目录接口，不能证明所选远端 profile。

这不是模型答错，也不是可以通过删除 AGENTS、换账户目录或降低权限规则来绕过的问题。当前真实 Codex 生成计数继续为 0。

## R4 增量

官方[配置参考](https://learn.chatgpt.com/docs/config-file/config-reference)列出了 `features.code_mode.enabled`、`features.multi_agent`、`features.apps`、`features.memories` 和 `tools.view_image`。这些成为新的候选关闭项；原 shell/web/memory/agents 及逐项 MCP/app 关闭覆盖继续保留。

文档存在这些键，不证明实际 CLI 0.163.0 支持或真正关闭桌面注入工具。必须先读实际安装构建的配置 schema，记录 CLI/binary/hash/schema，再由 `plan_codex_isolation.py` 判断显式属性支持。additionalProperties 通配不算支持证据。若当前 CLI 无法合法提供完整 schema/工具观察，继续记录 blocked，不临时换模型、provider 或账户根目录来“证明”。

```bash
python scripts/plan_codex_isolation.py --schema /absolute/actual-cli-schema.json --previous-observation /absolute/r3-codex-preflight.json --cli-version 'codex-cli 0.163.0' --model gpt-6-astra --output /absolute/new-isolation-plan.json
```

这个命令仅生成诊断计划，所有出口 `sufficient_for_generation=false`。不执行 CLI，不生成成功 proof。

## capabilities/2 必需证据

1. binary、profile、全部有效配置来源与覆盖 hash；CLI/model/provider 身份。
2. 真实所选 provider 的模型目录原文件及字节 SHA；model 必须出现在其 models/data 条目。
3. 在真正发送前捕获的原始 request 文件及字节 SHA；model 一致，明确 tools=[]，无未经检查的 agent/harness/environment。
4. 同一运行配置的完整实际工具面，空列表而非“输出里没调用工具”；原策略与 AGENTS 保留。
5. 来源可信的 observer 标识和时间，有效期有限；fixture=false、provider_override_used=false。
6. 原始工件回读与 observed/proof 双向绑定。旧 /1 proof 不继续生效。

`validate_codex_proof` 不再接受只有两个自填 SHA 的声明；原始文件缺失、被改、目录无所选模型或请求仍含工具均拒绝。单测 fixture 明确标 true；argv/超时单测显式 mock 掉证明检查，不生成可误用为真实记录的成功夹具。

文件 hash 证明内容一致性，不能证明记录是实际捕获。可信 observer、同一真实 provider 与未改动的运行策略仍需原机证据。禁止把手工改字段或 mock 请求改称真实证明。

## 对照设计

对同一冻结事实和相同 style policy，记录 host canonical、Qwen prompt-only、Codex reference、匹配 legacy 四个臂。保持缺失/阻塞可见；host canonical 是模板基线，不冒充旧模型输出。温度、thinking、模型目录、CLI/模板身份及 wire 均有记录。不要对不同 provider 的内部提示差异宣称纯模型胜负。

评审先判事实可用，再盲化自然度与可采用性。数字不得跨分母： attempted、已返回、事实合格、人审合格、成对可比较各自报告。远端 stop 未确认时停止后续臂并交由原状态协调，不自动重试形成并发。

若工具面依然无法证明为空：回传准确观察并继续 Qwen+人工 gold 工作；silver 仍为 0。可另提原生 API 表达参考路线，但它与 Codex CLI 是不同实验臂，不能替换后继续用原 Codex 成绩名称，本包没有新增该 API provider。
