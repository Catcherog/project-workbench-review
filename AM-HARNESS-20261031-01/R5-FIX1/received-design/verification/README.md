# 验证范围

`r5-original-116-tests.log` 是对固定R5源码的独立离线复跑：116项，0失败、0错误、0跳过。使用Python 3.12.14、Linux；它不替代原机MLX、Qwen或飞书验收。

`r5-independent-review.json` 记录对应审核提交、源码依据、Git blob核验、数据重新计数和限制。

`repro_holdout_gate_result.json` 是修复前最小控制流反例的实际输出。只有私有mechanics检查、原机元数据探针被假定通过，最后的trainer启动被截获；真实训练与模型调用均为0。合成24/8来自既有单测夹具，不是真实gold。

`repro_holdout_gate.py` 可在原固定R5源码上重现：

```bash
AM_R5_REPRO_PACKAGE=/实际位置/未打补丁的am-style-r5 \
  python verification/repro_holdout_gate.py
```

脚本需原R5测试及baseline依赖，所有输出只落临时目录和脚本同目录；不会连接原服务或启动trainer。相较最初运行版，仅添加了显式源码路径环境变量，控制流未改。本脚本用于说明原缺口，修复后的拒绝启动由新增回归覆盖，不能用它在修复后“仍成功”作为通过标准。

最终补丁的测试与逐文件绑定见本目录其他结果以及包根清单。私人声明原件、独立测试输入、模型和运行时凭据不在本包中。
