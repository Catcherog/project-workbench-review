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

## R7 原机训练与评测控制

当前原机另设私有 `training-window-r7` 请求目录，仍由同一个 bridge 消费者执行。原 `resource-window-r6` 只接受 diagnostic／recover，契约保持。两种控制共用原 Store、ModelCoordinator、维护围栏及锁，不并行开启窗口。

`tools/training_control.py` 提供 train、eval-mlx、cancel、recover、inspect；写入请求须带 `--execute`。train 绑定具体 R7 私有 plan、真实文件 SHA、UUID、run 目录和最多 3600 秒的请求有效期。eval-mlx 另绑定已完成的 pilot plan、三组评测 plan 和 arm。请求重复或输入改变均拒绝；独立材料不齐时不会卸载 Q8。请求文件写入成功仅表示已提交，不代表已训练。

执行回调使用计划中的 Python 与原 `am-style-r5/run.py`，显式指定当前宿主和训练源码。R4 fit／reload 仍各自取得原 OriginalLease，训练实现、mechanics 哈希和 24／5 GiB、22 GiB、swap 规则保持。空闲时已卸载的 Q8 在同一围栏和原锁内精确补载，再建立卸载窗口。

监督记录真实 CLI、R4 parent、fit／reload（评测则为 MLX worker）的 PID、PGID、OS 创建时间、完整参数和源码绑定。完整模型需求覆盖普通聊天、harness、AM／source_wait、群查询、信息提取及私有模型探针；原路由判定为纯 I/O 的导航、采集和投递继续处理。原 R4 内部的既有队列规则没有放宽。

取消时先冻结已核验的启动进程组，停止属于该请求的各独立 worker，再核验全部组消失。进程身份或停止状态未知时保持 recovery_required；不恢复 Q8，不清除其他原因的暂停。原机重启后的 recover 从持久化进程记录重建检查，只恢复原服务，从不续训。

恢复命令使用实际提交回执中的 request_id：`tools/training_control.py recover --request-id <原请求UUID> --execute`。取消使用同一工具的 cancel；inspect 只读。脚本须用原计划绑定的 Python 运行。真实训练仍须通过未修改的独立测试声明门禁；隔离进程测试不能当作训练或业务验收。
