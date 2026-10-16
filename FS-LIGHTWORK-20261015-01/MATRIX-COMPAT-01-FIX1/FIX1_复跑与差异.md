# FIX1 复跑与最小差异

只修改运行源码两处：`src/aggregate.mjs` 的快照语义行集合；`src/read-live.mjs` 的逐命令失败隔离、源范围校验及回执。没有组件UI源码修改。`src/replay.mjs`、`src/verify-evidence.mjs`、原26项测试保持原字节。

复跑命令（全部离线，Node.js 18+，本轮本机v24.21.0）：

```sh
node --test tests/aggregate.test.mjs
node --test review/additional.test.mjs
node --test tests/fix1-reader.test.mjs
node src/replay.mjs
```

第二条是GPT原样7项测试，内部把当前的两份源码复制到临时目录，通过假CLI触发真实读取程序分支；生成的reader回执属于本轮修复后结果。第三条是本轮11项保护测试，同样只使用假CLI；真实身份、宿主和对象清单未调用。不要直接执行read-live.mjs来重复访问真实来源。

| 证据组 | 结果 | 归属 |
|---|---|---|
| gpt-independent-review/review/* | 原26通过；新增7项3通过4失败；原8小时重放 | GPT独立复审，原样保留 |
| evidence/before-* | 26通过，新增7项仍3通过4失败 | Codex在修复前独立目录复现 |
| evidence/after-original26.txt | 26/26 | 修复后原回归 |
| evidence/after-additional7.txt | 7/7 | 修复后GPT反例与对照 |
| evidence/after-reader-guards11.txt | 11/11 | 修复后身份/范围/失败回执等保护 |
| evidence/after-snapshot-checks18.json | 周/月各9项，共18项 | 修复后公开快照重放 |
| review/reader-*.json | 项目查询/节点失败均保留8小时，成功、失败回执已保存 | 修复后假CLI结果 |

具体错误判定：非零退出码只有错误摘要，不把stderr里的自然语言当成权限证明；该情形为request_failed。仅明确结构化permission_denied返回标为permission_denied。两类均不当作0，原始错误正文不输出。全局authenticated/host校验失败或返回源身份与固定作用域不符会停止；这不是跨系统查看者身份映射证明。

新完整快照删除行、同版本真实冲突、无版本真实冲突、合法不同记录及分页覆盖规则均继续由原测试保护。B01采用完整源键与原业务内容集合去重，没有按人员/周/小时粗粒度合并，也没有把旧快照做并集。

修复后的进程在成功取得T02且独立来源失败时正常结束并输出partial状态、覆盖缺口及单命令回执；全局校验或主来源失败返回非零状态。主来源失败输出的单元格为空，不复用缓存。后续有非空项目记录仍标mapping_unverified，本轮未关闭C08。
