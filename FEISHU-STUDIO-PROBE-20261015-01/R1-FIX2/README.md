# R1-FIX2 最小离线复核包

只修复FIX1-B01。真实模型、真人发送新增均为0；正式服务不改。先读 `00_当前交接.md`。

固定基线是 `cc5f5d059a4f104c14a01eaed57f4e5d75419e15` 下的 `FEISHU-STUDIO-PROBE-20261015-01/R1-FIX1/`。最终源码见本目录，精确增量见 `proposals/fix2-lifecycle.patch`。未变的少量依赖保留用于完整回归；未附旧迁移ZIP和无关历史。

环境需Node22+且实际支持node:sqlite，目标为macOS/Linux。本轮实测Node24.21.0/macOS；不安装或升级环境，无第三方npm依赖。

```sh
node --test tests/reviewer-stop-contract.test.mjs
node --test tests/fix2-termination-state.test.mjs
npm test
```

分别应得到6、13、78项通过。测试只有合成状态、确定性假执行器和自有短期子进程，不使用模型、飞书或正式网络。原59项仍在；纯函数fixture增加明确logical-only声明，没有删除、跳过或改低原断言。

```sh
node src/import-budget.mjs
node src/import-budget.mjs
node src/start.mjs
```

预算导入只读历史快照并维护本目录独立账本，两次均保留3次历史；这不是本轮真实模型额度授权。本轮新增许可为0。关闭态start预期退出2。

未知状态不会靠删锁、删除账本、复制目录或迁移清零。终止账本必须伴随任何未来获准的运行状态交接，或让交接明确阻塞；本代码包不携带真实runtime。仅当原任务关闭/worker已settled且同主机可信检查充分时，`reconcileTermination`才能释放；它不kill任何PID，也不自动重做业务任务。保存原停止回执与新对账回执，二者不要合并成一条“已完成”。

原B01—B04、C1—C4和Studio保持FIX1既有状态，本轮不推进。公共文件经过脱敏；原始个人任务/聊天、认证、真实身份和正式数据未包含。校验清单覆盖本目录除清单自身外所有负载。发布与执行端读回不代表GPT已独立复审。
