# 后训练主线独立复审
日期：2026-11-03（Asia/Shanghai）。
审核提交：78407b22c18dbb17c0bd79f1c8486d896bf5ebe2。
源提交：63d8afdcac2ca440846cb22237fc5b097a074941。

## 结论
R5-FIX1 限定补丁复审通过。实读四文件变化、实际源码、输入绑定、原 R4 训练/资源模块和原机证据；没有发现该轮要求范围内需要阻塞返工的新缺陷。通过仅指“训练前冻结独立测试”门禁与准备链路；真实 pilot、效果人评、新表达宿主集成、业务验收仍未完成。

## 本次独立验证
- 175 份必要审核文件下载到 baselines/harness，逐个与固定 GitHub blob SHA 核对一致。
- 四份实际源文件的 SHA256 和长度均匹配 received-design/INPUT_AND_PATCH_BINDINGS.json。
- baseline/PROVENANCE.json 列明的 37 个文件全部匹配；provenance 文件自身另在固定 GitHub 字节检查内。
- 在 Linux / Python 环境，直接运行公开实际 R5 源码的 134 项 unittest：134 通过、0 失败、0 错误、0 跳过，63.817 秒，模型调用 0、训练 0、生产修改 0。日志在 audit-harness-validation/tests.log，结果在 summary.json。
- 原机 17 项 R4 训练合同、2 项真实临时 flock 顺序检查为已读取的 Codex 证据；本次未在 Mac 重做，不能改写为云端实测。
- 没有本轮上传 ZIP 的直接字节；本次确认的是 received-design 中绑定与固定提交源码，不能声称重新验算附件 ZIP 的 SHA。

## 判定依据
1. holdout_gate.py:40–51 对同一次文件读取同时解析/哈希；159–178 每次重建绑定，不接受缓存绿灯。
2. holdout_gate.py:75–107 绑定实际 gold snapshot，检查 train/dev 与 sealed_test 组别、父组和近重复。
3. holdout_gate.py:109–121 要求声明绑定 case manifest、有声明者/带时区时间、不晚于绑定时间、保留原件 SHA 一致。hash 不证明身份真实性和未披露调参历史，代码已明示这项限制，真实人类声明仍须执行端核验。
4. pilot.py:325–361 明确分离 metadata_ready、execution_gate 和 resource_gate；缺 holdout 可以准备/预检，但 ready_for_launch 保持 false。
5. pilot.py:364–397 在任何 metadata subprocess 前先检执行输入，probe 后再读并比较 plan/gate，变化不能沿用旧报告。
6. cli.py:268–276 两种入口都走 execution_argv；缺材料返回 2 且不会运行 trainer。
7. training/mlx_r4_resources.py:69–87 先取原非阻塞 flock，再检查 before_load 资源；原值 24 GiB，运行中 5 GiB、swap 增长不超过 1 GiB，业务到来停止。
8. training/mlx_r4.py 的 execute_phases 只有 fit 停止确认后才启动 reload；training/mlx_r4_runtime.py 在 OriginalLease 内才 import MLX / load model。

## 合并设计需继承的边界
- 原 R4 不认识 holdout gate；R5 返回的原 R4 argv 只表示产生命令时检查通过。新维护窗口若排空/卸载模型耗时，必须在真实启动前重新进入原 pilot-execute，不缓存或直接重放旧 argv。
- 新窗口不能外层长期持有同一个 model-coordinator.lock 再等待 R4，否则 R4 非阻塞取锁必然失败。应由维护标记阻止普通推理准入，R4 worker 自取原锁并重新查资源。
- 允许单独做资源诊断/恢复，不具备训练启动 API 的诊断模式可在 holdout 不齐时执行用户已授权的停载可行性检查；训练模式仍必须先满足完整独立测试门禁。
- 源码和原 Q8 身份、生产开关、唯一消费者分别验证。门禁通过不等于服务集成或训练收益。
- 24/8 gold 和三轮已认可反馈应直接复用，不要求重复评分，也不把这些开发材料改名为独立测试。

## 内存证据
evidence/runtime-final.json，2026-11-02T10:01:45Z（北京时间 18:01:45）：
- physical_memory_GiB=64；
- original_resource_metrics.available_memory_GiB=14.4490966796875；
- memory_pressure=1，swap_used_GiB=0.6519775390625，pending_business=0；
- /api/ps 原 Q8 名称 qwen3.8:27b-bartowski-q8_0，digest=52b6ea169d93070c185373f6ff9ec33a7a5e88cfe9c844fc225ed4214683baef；
- size / size_vram=27129376930 bytes（约 25.27 GiB），runner=llamacpp；
- llama-server RSS=28.461334228515625 GiB。
这足以支持“原 Q8 常驻为主要占用候选，值得做卸载前后对照”，不足以证明卸载后必达 24 GiB。RSS 与模型映射不应直接相加或等同可回收内存。需要同一指标、同一窗口卸载前后测量，并由原 R4 在真正启动时重新放行。

## 来源
- https://github.com/Catcherog/project-workbench-review/blob/78407b22c18dbb17c0bd79f1c8486d896bf5ebe2/AM-HARNESS-20261031-01/R5-FIX1/00_当前交接.md
- https://github.com/Catcherog/project-workbench-review/blob/78407b22c18dbb17c0bd79f1c8486d896bf5ebe2/AM-HARNESS-20261031-01/R5-FIX1/CHECKS_SUMMARY.json
- https://github.com/Catcherog/project-workbench-review/blob/78407b22c18dbb17c0bd79f1c8486d896bf5ebe2/AM-HARNESS-20261031-01/R5-FIX1/evidence/runtime-final.json
