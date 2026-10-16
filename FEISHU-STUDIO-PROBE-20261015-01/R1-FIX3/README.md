# R1-FIX3 审核包

先读 [当前交接](00_当前交接.md)：**双角色真实调用未执行，最低隔离组合阻塞；A 修复和 B 离线接线完成。**

Node 22+ 且支持 node:sqlite；本机实际 Node 24.21.0/macOS 27.0.1，CLI 未升级。无新增第三方依赖。

- `npm test`：84 项离线检查；包含字节未改的原 78 项。
- `node --test tests/dual-role.test.mjs`：同一 broker 选择两角色，使用假执行器及本地回执，**不调用真实模型**。
- `node src/dual-role-probe.mjs`：真实入口关闭，预期退出 2。
- `node tests/minimum-isolation.mjs`：可选 macOS 非模型诊断；本机单项通过、组合失败，预期退出 2。不会读取认证内容。

A、B 证据分目录；旧证据仅按固定 FIX2 SHA 引用。包内保留原回归必需的依赖，没有正式库、凭据、私人原始任务、旧迁移 ZIP 或运行账本。SOURCE_PROVENANCE 区分本轮源码、A 冻结源码和审核基线。校验清单覆盖自身以外全部公开负载。

新目录复制不能重置历史计数或未知状态；本机运行账本仍保留 3 次历史，未公开。发布不代表安装或 GPT 审核通过。待 GPT 独立复审，到此停止。
