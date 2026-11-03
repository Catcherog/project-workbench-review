# AM R6 资源窗口与合并验证包

本包与原工程源码增量一起安装；保持生产表达 off。完整设计和原机执行交接位于审核目录的 `docs/`。

## 只读盘点（仅原 Mac）

```bash
cd /absolute/current/repo/am-integrated-r6
python3 -m am_training_window.mac_probe snapshot --output /absolute/private/window/before.json
```

## 离线验证

```bash
python3 /absolute/current/repo/am-integrated-r6/tools/run_validation.py --repo /absolute/current/repo --output /absolute/private/r6/offline-validation --with-r5
```

脚本复用当前原工程，使用临时数据库、合成平台与 provider。它不安装依赖，不访问生产数据库，不运行真实模型或训练器，不发送真实消息。原服务支持模块及既有固定回归测试须存在。

`tests/followup` 为文字批准与语义回归，`tests/integration` 为事实投影／原出站接线，`tests/resource_window` 为只读解析、两阶段维护、门禁及恢复合同。

## 原机端口

`ExistingCoordinatorHost` 直接使用原 Store 和 ModelCoordinator。Codex 需以真实管理器绑定 fresh `read_observation`、精确 `ExactProviderLifecycle.suspend/restore`、原 `pilot-execute` 回调和 fit/reload 进程组停止证明。公开基线没有包含实际 llama.cpp proxy/manager 控制端，不能将单测假端口用于生产。

`TrainingWindow.diagnostic()` 无 trainer 参数，可先回答临时释放 Q8 是否有足够内存；`train()` 在暂停 Q8 前和启动前都重查原 R5，并交还原 R4 在原锁内做资源检查。原24 GiB／5 GiB／swap增长1 GiB策略、原训练参数与模型身份不变。

新增回归案例均属于已暴露开发素材，不是新gold、用户评价或独立holdout。训练、效果人评、宿主接入和业务验收分别记录。
