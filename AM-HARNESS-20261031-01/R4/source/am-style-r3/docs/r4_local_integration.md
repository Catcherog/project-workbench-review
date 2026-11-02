# R4 原机接入说明

实现基于 R4 v4.0-design.1 原包，原包 ZIP SHA256 为 `110127ab1519921d80956ecba5904731f54798a6d4eaab373c6a787f1afee179`。本轮源码从当前有效版本 `73c1f9e11ec8b1ea9c3e36060a2522fab3676480` 增量修改，保留 R3 之后的跟进模块。收到的设计、离线结果和原机实测结果分别保存。

`am_conversation/terminal.py` 核验引文与字段、单项目查询字段覆盖，并将两类当前不支持的确认预览保留在原路径。`am_response/gateway.py` 在原 outbox 事务内绑定真正发送的正文，正文变化时 outbox 与投影共同回滚。没有新建消费者或发送通道。终端表达默认继续关闭；自然语法扩展仅在本轮隔离实验显式使用。

新增 `generate_r4_projected_seeds()` 从可信的合成场景输入生产新 frame，将测试开始时间与时长映射为 `start_and_duration`，并保留原 R3 构造函数、gold、分组和旧 prompt。真实业务里的任意模型追问仍不是 typed gap 证据，原 terminal projector 对其继续保守回退。新旧 frame 与人工认可不能互相挪用。

训练代码与 `am_style` 在原工程中位于不同目录。已将 prompt builder 指纹读取改为当前实际导入模块的文件，而不是假定两者相邻；未放宽任何 hash、数据、内存、优化步数或重载门禁。运行时使用原 Python 依赖环境，并把两处源码目录以绝对路径放入 `PYTHONPATH`，供新 worker 继承。

R4 实测与未完成状态以 `AM-HARNESS-20261031-01/R4/00_当前交接.md` 及其固定审核提交为准。`docs/execution_plan.md` 等来自收到的设计包，文中的“本轮未运行”指交付设计时状态，不能代替本机最终结果。
