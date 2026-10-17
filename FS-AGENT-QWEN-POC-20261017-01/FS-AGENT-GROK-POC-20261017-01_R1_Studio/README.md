# 飞书统一 Agent 入口 · 本地 Qwen PoC

FS-AGENT-GROK-POC-20261017-01 / R1；任务编号保留历史命名。更新于 2026-10-17，Mac Studio。

**真实 P1 已通过，PoC 已接入既有 AM221D221。57 项 PoC 离线测试、8 项原桥接测试通过。真实 `/doc sample` 没有回复，P2 未通过：最新事件是富文本 `post`，当前入口只接受 `text`，任务尚未入队。**

新窗口先读 [当前交接](handoff/00_当前交接.md) 和 [START_PROMPT.txt](START_PROMPT.txt)。详细边界见 [有效需求](docs/01_有效需求与覆盖关系.md)、[验证记录](docs/02_功能验证记录.md)、[运行说明](docs/03_运行与飞书操作.md)。`inputs/` 是历史来源，不能覆盖后续用户决定。

当前复用登录账户和现有单条飞书长连接，普通私聊行为保留；PoC 的 `/doc`、`/progress` 仅限两位已核实测试者。PoC 数据单独保存于 `~/.local/share/local-qwen-feishu/poc/`。不创建新账户、新应用或第二个消费者。

模型为 `qwen3.8:27b-bartowski-q8_0`，接口 `http://127.0.0.1:11434/v1`，Ollama `0.40.5`，实际模型摘要已固定。当前全局单路、每人 1；目标两路尚未实测。不需要 Grok 登录，不更换或下载模型。

1.0.9 两项通讯录只读权限已通过管理员审核，并已读取两位测试者状态及准确部门。1.0.10 菜单卡片回调最后观察为审核中，无新增 API 权限。**以后提交任何审批申请前先告知用户内容和原因，尽量合并相关配置。** 本次命令未入队与菜单回调审核是不同事项。

开发检查：`.venv/bin/python -m pytest -q`。模型连通检查：`./scripts/service.sh check-api`，会产生一次合成推理。服务管理使用相邻 `local-qwen3.8/feishu-bridge/service.sh`；不要单独运行本项目 `serve`。

旧 sudo Grok 安装脚本已停用；`provider.py`、`environment.grok.example.json`、`service.grok.sh` 仅作历史实现。交付源码不包含私有凭据、准确个人 ID、运行库或后台截图。原 ZIP 校验清单 `inputs/MANIFEST.imported.sha256` 只对应原件。
