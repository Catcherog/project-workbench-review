# R1-FIX1 独立修复与迁移检查包

先读 `00_当前交接.md`。真人入口和真实模型探针默认关闭；正式补丁仅供审查。没有第三方npm依赖。

实际环境：MacBook Pro、macOS27.0.1/arm64、Node24.21.0、Codex0.162.0-alpha.17.2。目标Studio及其他版本需重新验证；Node须实际支持 `node:sqlite`。

```sh
npm test
node src/import-budget.mjs
node src/import-budget.mjs
node src/preflight.mjs
node src/start.mjs
```

测试是合成/离线；会启动确定性假可执行程序与短期本地替身进程，不调用模型或飞书。预算重复导入保持历史3次；预检默认只读；start预期退出2。

明确指定本机已有Codex后可单独运行系统沙箱哨兵：

```sh
export PROBE_CODEX_BIN="/absolute/path/to/codex"
node tests/isolation.mjs
```

它不调用模型，只创建自有合成文件与一个短期loopback端点。不可把它计作模型路径隔离或Studio通过。

`src/local-probe.mjs` 和 `tests/model-isolation.mjs` 当前退出2，不消费模型额度。真实模型补证必须等B03前置充分后，在获准任务中用最终代码、同一启动构造器和严格判据执行；FIX1最多新增4次、单并发180秒、原任务累计20次。不能删计数库或通过迁移重置余额。

源码：`process.mjs`负责实际进程终止及退出确认，`broker.mjs`负责消息阶段与IO边界，`worker-adapter.mjs`验证并投影四字段结果，`isolation-evidence.mjs`判定严格证据，`launch.mjs`是唯一exec配置构造器，`budget.mjs`管理实际模型额度。离线假执行器由测试控制器固定，不能由消息或模型指定。

`proposals/`包含候选补丁、准确指纹、必要源上下文、测试钩子、未启用的配置示例。不要把它当成已安装程序，或直接在正式目录运行git apply。恢复/回退和未知发送规则见交接说明。

包的清单覆盖除清单自身外的所有发布负载。原始任务、runtime、private、真实身份与凭据不在包中；公开证据路径已脱敏，源码执行逻辑保持不变。
