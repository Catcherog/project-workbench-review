# 独立复审证据包（最小复跑材料）

固定审核 SHA：8b7c5e3d7d59aa5d1e0099d19e2613f92691df5e。

此包是 GPT 的独立复审材料，不是 Codex 原 73 份材料的全量副本，不是修复版，也不是原矩阵代码。所有数据为原公开脱敏投影或本轮离线合成数据。8 个转录文件的 Git blob 和原 manifest SHA-256 已复核匹配。

运行环境实测 Linux / Node.js v22.16.0。无需安装外部依赖。

```sh
node --test tests/aggregate.test.mjs   # 预期 26 通过
node src/replay.mjs                   # 脱敏快照：周、月各8小时
node --test review/additional.test.mjs # 旧版预期3通过/4失败，退出码1
```

新增测试以临时 PATH 中的假 meegle 进程验证原读取脚本，只包含合成身份；不访问真实飞书。不要直接执行 src/read-live.mjs。src/verify-evidence.mjs 仅留存审读，本包没有运行其全量前后检查所需的材料；本次没有运行该脚本。

先阅读 00_GPT独立复审与FIX1任务.md。关键结果在 review/review-summary.json；精确转录指纹在 review/transcription_hashes.json；失败反例在 review/additional.test.mjs，回执在相邻 TAP/JSON 文件。

本包未包含任何已实施修复。后续任务待牧翊确认转交；不能据此发布、扩权、更新原组件或写入工时。
