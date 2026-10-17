# 飞书与 Studio 本地 Qwen 接入

2026-10-17 续接更新：本服务已接入相邻 `FS-AGENT-GROK-POC-20261017-01_R1_Studio` 的 `EmbeddedPoC`，使用同一个 SDK client、长连接和 worker；普通私聊行为保留。两人合成路由的入口为 `/doc`、`/progress`、`/menu`，`/chat` 返回普通聊天，数据单独保存在私有 `poc/` 子目录。

**当前 PoC `/doc sample` 真实无回复，未验收通过。最新事件是富文本 `post`，目前桥接与 PoC 都只接收 `text`，已到达但未入队；先按相邻项目的 `handoff/00_当前交接.md` 修复。** 下文 11:25 验收记录仅为此前普通聊天，不能计入 PoC P2。

原 `.venv` 已 editable 安装相邻 PoC 项目，移动该源码会影响服务。迁移时先安装 bridge 依赖，再安装 PoC 包，并重新验证私有配置、准确测试身份和单消费者；不能复制原机器运行库或直接套用原绝对路径。1.0.9 两项只读权限已批准，1.0.10 卡片回调最后观察审核中。以后提交审批先告知用户。当前 57 项 PoC 测试及 8 项桥接测试通过，富文本缺口尚未修复。

2026-10-17 11:25（Asia/Shanghai）：App AM221D221（`cli_REPLACE_WITH_EXISTING_APP_ID`）已完成真实私聊端到端验收。飞书发出 `ST-112401，17 加 25 等于多少？只回复计算结果。` → Studio 收到并通过事件校验 → 本地 Qwen3.8-27B Q8_0 生成 `42` → 原消息回复接口成功 → 飞书客户端可见 `42`，本地状态为 `done`。验证记录见 `verification-20261017.json`。

本地模型适配器的合成测试“17 加 25”返回 `42`。用户随后明确要求每位与机器人对话的人都可收到模型回复，当前访问模式已改为 `all_private_users`。8 项离线测试通过，新增验证不同用户的上下文隔离；官方 SDK 的合成事件反序列化到回复流程也通过。

## 当前运行方式

- 固定调用本机 `http://127.0.0.1:11434/api/chat`，模型 `qwen3.8:27b-bartowski-q8_0`，不下载模型。
- 不加自定义系统提示词，关闭思考，16K 上下文，单次最多生成 1024 tokens。
- 接受所有能访问该飞书应用的用户的文字私聊，各用户上下文按租户、应用、会话、用户分开；群聊和非文字消息不处理。此设置不改变飞书发布范围，也不赋予任何公司资料读取权限。
- `/new` 清除当前会话的上下文；`/help`、`/status` 返回接入说明。
- 最多使用最近 4 轮历史，输入最多 6000 字符；本地历史逻辑保留不超过 24 小时，去重元数据 7 天。磁盘备份和底层文件系统的保留不受本程序控制。
- 未连接公司项目资料、云文档、工具或其他 Agent；未进行微调。
- 当前用户登录后自启，异常退出自动重启。`caffeinate -i` 仅在该服务运行时阻止空闲睡眠，未修改全局电源设置；关机、主动睡眠、退出登录或断网会中断服务。
- Secret 在用户私有目录的 0600 文件中；不写入代码、日志或交接包。

## 原 Studio 上管理

```sh
zsh '/Users/REPLACE_WITH_LOCAL_USER/Documents/ChatGPT/多agent系统/local-qwen3.8/feishu-bridge/service.sh' status
zsh '/Users/REPLACE_WITH_LOCAL_USER/Documents/ChatGPT/多agent系统/local-qwen3.8/feishu-bridge/service.sh' stop
zsh '/Users/REPLACE_WITH_LOCAL_USER/Documents/ChatGPT/多agent系统/local-qwen3.8/feishu-bridge/service.sh' start
```

停止后不会立即自动重启，但下次登录仍按 LaunchAgent 启动。

- LaunchAgent：`~/Library/LaunchAgents/local.qwen.feishu.plist`
- 私有配置：`~/.local/share/local-qwen-feishu/config.json`
- 密钥文件：`~/.local/share/local-qwen-feishu/secrets/app_secret`
- 状态与会话库：`~/.local/share/local-qwen-feishu/state/`
- 无正文日志：`~/Library/Logs/local-qwen-feishu/`

`connection-status.json` 是最近连接状态变化的记录，不是持续心跳。结合进程、TCP 连接和新消息验收判断健康；`frame-status.json` 表示收到数据帧，`event-status.json` 仅含校验布尔值和消息类型，`worker-status.json` 只含计数。缺少这些文件时表示没有相应观测，不能据此宣称飞书未发送过事件。

## 在另一台 Mac 接手

1. 先阅读交接包的 `先读我.md` 和证据索引。仅检查文件与本地模型时，不要启动飞书长连接。
2. 原 Studio 已在运行本应用连接。迁移前必须停掉它，核实其他消费者也已停止，避免同一应用多端分走消息。
3. 使用 Python 3.12 创建独立 `.venv`，按 `requirements.lock.txt` 安装依赖。`.venv` 未打包，需要重新创建。
4. 将 `config.example.json` 复制到私有目录，填入新 Mac 的绝对路径。当前 `access_mode: all_private_users` 允许该应用的所有用户私聊；如另有要求改回 `allowlist`，必须填入飞书核实的真实 open_id，不能使用占位值。
5. 从飞书开放平台安全取得 App Secret，写入私有文件（目录 0700，文件 0600）；不要发到聊天或提交到 Git。交接包不含 Secret 和令牌。
6. 确认只有新 Mac 消费该应用事件后，才把 `exclusive_consumer_confirmed` 设为 `true`。
7. 在本机模型冒烟测试通过后，前台运行 `.venv/bin/python bridge.py --config /absolute/private/path/config.json`，先验证本人私聊收发，再配置新机器 LaunchAgent。包中的原机器 plist 是证据，不能直接当新机器安装配置。

## 事件排查与验收记录

初次测试中用户报告已发送，但程序没有收到数据帧、没有事件诊断记录、队列为空。后续确认心跳正常，机器人成功发送诊断通知，读取此私聊记录时没有今日算术问题。客户端检查发现此前测试文字仍在输入框草稿中；将带唯一编号的问题实际发送后，消息正常到达 Studio 并收到 `42`。因此本次无需修改飞书订阅、密钥或权限。扩大用户范围是用户明确提出的新需求，与修复投递不是同一项变更。

后续故障时依次核对 `heartbeat-status.json` → `frame-status.json` → `event-status.json` → SQLite 状态 `done` → 飞书可见回复。已订阅的已读和 reaction 事件只确认接收，不触发模型回答。当前真实账号验收覆盖本人私聊；其他用户的访问分支和上下文隔离通过合成测试，尚未进行多真人账号或高并发压力验收。原 Studio 的本地队列和敏感运行库不在交接包中。

SDK 上游：https://github.com/larksuite/oapi-sdk-python
