# AM R9-FIX2：准确挂载目标配置与离线验证边界

本说明对应 `document_target.py`、`meegle_port.py` 与 `document_delivery.py`。示例、测试中的工作项、字段、候选和业务编号均为合成数据；本轮没有调用真实 Meegle API，没有更换原机目标，也没有执行真实业务写入。配置示例不是可直接投入运行的原机配置。

## 配置分工

| 配置键 | 含义及独立读回要求 |
| --- | --- |
| `space` | 授权空间 key；项目和交付物返回的 `owned_project.key` 必须分别匹配。 |
| `project` / `project_type` | 项目工作项 ID / 工作项类型 key；独立读取项目属性，验证 ID、空间及类型。这里的 `project_type` 是平台工作项类型，不是文档模板里的 IRAD 等业务分类。 |
| `project_code` | 预期业务编号；项目真实标题必须能唯一解析出同一编号。配置中的编号不能代替实际读回。 |
| `node` / `deliverable` / `type` | 节点 key / 交付物 ID / 交付物类型 key；节点必须属于请求的项目，返回的节点 key 必须一致，其原生下级工作项列表必须包含交付物；再核对交付物属性及项目、节点关系字段。 |
| `document_type` | 预期文种，限 `charter`、`change`、`closure`、`test`。正式目标发现入口仍只接受前三类；`test` 保留已有测试报告路径。 |
| `document_kind_field` | 实际存储文种身份的字段 key；字段元数据和实际单值必须共同证明文种。 |
| `document_link_field` | 实际追加文档的写入字段 key。本版本沿用附件上传和附件列表更新流程，只支持 `file` 类型；没有新增 URL 列表写入器。 |
| `project_field` / `node_field` | 交付物上的项目与节点关系字段。即使原生节点成员列表匹配，关系字段缺失、含多项目或不一致也会阻断。 |
| `approval_field` / `delivery_mode_field` | 审核、交付方式字段；候选与当前值都需核验。原有未审核保护继续保留。 |
| `unreviewed_value` | 已审查的“未审核”候选 ID。提交时实际审核字段必须为该值。 |
| `document_type_bindings`（可选） | 已由管理员审查的 `{候选ID或文本值: 标准文种}` 映射。不会绕过字段类型、候选存在性或实际读值校验；候选的可识别文种标签与映射冲突时拒绝。 |
| `verified_empty_revision`（可选） | 保留旧机制：只有人工在真实界面验证的初始空附件槽，才可绑定该次完整目标 revision。缺失字段不会自动当成空列表，也不会自动生成该配置值。 |

文种、写入、项目关系、节点关系、审核、交付方式这六个字段角色必须使用不同字段。旧 `document_field` 可以继续存在，但只能与显式 `document_kind_field` 相同；旧 `attachment_field` 只能与显式 `document_link_field` 相同。旧字段不会补全新字段。只含旧字段、两个别名互相冲突或把 URL 字段当文种的配置均停止挂载。

迁移也影响以 `target_alias` 绑定 `document-business.json` 的 `project_snapshot` 信息来源：`ExistingMeegleReader` 复用同一 `_state` 验证，因此这些已有别名也须先核验、补齐明确配置。独立的完整 `MeegleProject` 项目采集路径不依赖这份挂载别名配置，不受此次新增字段要求影响。

## 当前严格支持的 metadata 和值形态

使用现有读取命令：`workitem meta-fields --project-key <space> --work-item-type <type> --page-num <page>`，最多 20 页。每页必须有 `list` 数组以及布尔型 `pagination.has_more`；分页没有完整结束不能用于授权。允许现有信息适配器使用的分组字段定义，重复的目标字段定义会阻断。

节点响应也必须明确返回布尔型 `pagination.has_more: false`。缺失、非布尔或仍有分页的节点读取不能证明本次完整目标。

读取期限与取消检查共用一个 `ContextVar` 上下文：目标发现的原 `deadline`/`guard` 覆盖所有别名、metadata 页、`resolve` 和 `document_identity` 复读。嵌套读取只能缩短期限。每个 CLI 调用前后都检查取消/有效期，subprocess timeout 为 `min(40秒, 剩余秒数)`；超过期限不会发起下一页或下一次读取。不在发现上下文内的 `_state` 也有 120 秒整体读取上限，并受当前 row 的 `expires` 限制。这里没有为每页重开预算，也没有提高全局超时。

| 字段角色 | 接受的 `field_type` | 接受的实际读值 |
| --- | --- | --- |
| 文种 | `text` 或 `select` | `text` 为非空字符串；`select` 为候选 ID 或 `{value, label?}` 单值。数组（包括单元素 URL 数组）不会转换为文种。 |
| 文档写入 | `file` | 现有附件对象列表，或其 JSON 字符串；保留原有文件 token、名称、类型、大小校验及下载字节哈希复读。 |
| 项目关系 | `work_item` | 单个 `{id: 项目工作项ID}` 对象。列表或缺少 `id` 的对象不支持。 |
| 节点关系 | `text` 或 `select` | 文本节点 key，或已验证候选的 value；必须与配置节点 key 相同。 |
| 审核 / 交付方式 | `select` | 候选 ID 或 `{value, label?}`。提交时审核仍须满足原有 `{value: unreviewed_value}` 保护条件。 |

`select` 元数据必须具有 `options: [{value: "候选ID", label: "标签"}, ...]`。候选 ID 不得重复；当前 value 必须在候选中，若响应包含 label，它必须与 metadata 相同。多选、树形选项、其他嵌套候选格式、URL/link 字段等均返回具体诊断。这里列出的是本适配器支持的窄契约，**不是已在原机确认的真实字段 schema**。如果原机使用不同的字段类型名或响应形态，应先导出真实 metadata 进行审查，再做精确适配；不能通过把配置预期值填成相同值来绕过独立读回。

无额外映射时，识别的文本或候选标签是：`项目章程`、`项目更改申请`、`项目变更申请`、`结项报告`、`项目结项报告`、`测试报告`。未加入按交付物名称猜测文种的兜底。

## API、诊断与回读

`resolve(principal, alias)`、`document_identity(principal, target)`、`commit`、`reconcile` 的调用形式保持不变。`document_identity` 仍返回 `{project_code, doc_type}`，但先重新读取完整绑定，任何版本变化都会拒绝旧 target。

`resolve` 在原 target 字段上增加：

- `document_identity`：由独立项目读回与文种值校验确认的身份。
- `document_kind_field` / `document_link_field`：明确分离的两个字段。
- `field_metadata_fingerprint`：六个相关字段的类型、选择候选等契约指纹。
- `binding_fingerprint`：项目、节点、交付物、字段角色、metadata 和文种身份的不可变绑定指纹。

可变 `revision` 仍覆盖交付物内容、附件列表、版本、节点状态和项目读回信息。写前和上传后、更新前均核对完整 revision。附件追加成功后，正常情况下附件列表和 revision 会改变；`reconcile` 比较不可变绑定指纹，同时要求目标文件唯一、既有文件 token 未丢失、实际下载内容哈希正确。因此不会仅因本次合法追加导致 revision 改变而误判失败。

原 journal、幂等键、结果未知状态与对账路径保留。新验证失败且尚未发起上传，仍标记 `BusinessNotStarted`；上传开始后无法确认的情况不自动重发。旧 journal target 没有新绑定指纹时，也不会被新代码直接认定为已确认，需原机审查对账。

`discover_targets` 保持只读。单一匹配且全量读取完成才返回 `available`；多个匹配为 `ambiguous`，仍需明确选择。如果某些别名核验成功但另一些失败，返回 `unresolved`，`targets` 为空；成功读到的候选仅放入 `reviewable_candidates` 供审查。没有写配置、创建候选或选择替代目标的行为。

原有通用诊断仍使用 `alias/stage/status/error_code`；本次验证错误可附加内容最少的 `detail`（如缺失配置键、字段 key、支持类型、失败检查），不包含业务正文或文档 URL。关键阻断包括：

- `BUSINESS_TARGET_CONFIG_INCOMPLETE` / `BUSINESS_TARGET_FIELD_CONFLICT`：含糊旧配置或角色冲突。
- `BUSINESS_METADATA_UNAVAILABLE` / `BUSINESS_FIELD_METADATA_MISSING`：真实 metadata 缺失或请求失败。
- `BUSINESS_READ_DEADLINE`：同一次读取的整体期限已到；不会继续下一页/别名。取消继续使用 `DOCUMENT_DELIVERY_SCOPE_CHANGED`。
- `BUSINESS_FIELD_TYPE_UNSUPPORTED` / `BUSINESS_FIELD_CANDIDATES_UNVERIFIED`：不支持或无法证明的字段类型、候选形态。
- `BUSINESS_PROJECT_CODE_MISMATCH` / `BUSINESS_PROJECT_CODE_UNVERIFIED`：实际项目编号不匹配或不唯一。
- `BUSINESS_PARENT_CHANGED`：配置交付物不在配置节点的原生下级列表中。
- `BUSINESS_PROJECT_RELATION_MISSING` / `BUSINESS_PROJECT_RELATION_UNVERIFIED`：项目关系字段未返回或不能证明唯一关联。
- `BUSINESS_DOCUMENT_KIND_MISMATCH`：实际文种与预期/映射不一致。
- `BUSINESS_TARGET_BINDING_CHANGED`：对账时身份或字段契约与 journal 中的目标不一致。

## 原机接续顺序

Codex 先用既有授权、既有固定 CLI 只读导出目标空间的字段 metadata、项目属性、原生节点及交付物字段。逐项核对上表并形成可审查的配置差异；原配置 member 不在 node、project code 不同、`document_field` 为 URL 列表、project field 没有返回的事实都应保留为阻断证据，不自动选新 ID。只有真实读回能证明同一项目、节点、交付物和独立文种/写入字段后，再由原流程进行选择、采用和正式挂载。

离线测试只证明合成响应下的校验和对账行为。它不证明原机 metadata 可读、平台字段契约已适配、真实挂载成功或独立业务验收通过。
