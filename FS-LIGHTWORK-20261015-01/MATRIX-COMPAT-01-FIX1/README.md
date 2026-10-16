# FIX1 审核入口

请从 00_当前交接.md 开始。当前源码与原26项、GPT原样7项、本轮11项保护测试均在根目录可复跑。gpt-independent-review/ 保留GPT复审包原字节，其旧源码仍应复现3通过4失败；不要把该区当作修复后的实现。

```sh
node --test tests/aggregate.test.mjs
node --test review/additional.test.mjs
node --test tests/fix1-reader.test.mjs
node src/replay.mjs
```

本轮全部故障测试仅使用假CLI。真实项目数据未重新取数，8小时为脱敏快照重放。当前不应直接运行 read-live.mjs，也没有原矩阵周汇总页面。云端仅实读入口和边界，未提交AI、保存、复制或发布。

公开包保留原复审文稿、代码、假CLI反例/回执和指纹，无真实员工ID、登录材料或源业务JSON。原云端完整页面文本留在本机；公开的是所需弹层文本、经过逐图检查的版本/复制菜单截图及元数据投影。内部链接使用example.invalid占位，不能当作实际测试入口。

source-file-map.json 记录来源与公开文件哈希；manifest.json 固定公开文件。GPT原包的原manifest单独保留，可再次验证22个清单项与ZIP指纹。源实现SHA与审核仓库SHA分别登记。
