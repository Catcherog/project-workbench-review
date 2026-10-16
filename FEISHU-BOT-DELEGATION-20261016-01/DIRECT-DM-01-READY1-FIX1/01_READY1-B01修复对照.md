# READY1-B01：批准与实际执行绑定闭合

原缺口：authority证明签名批准与manifest一致，transport证明平台与本机配置一致；缺少manifest与本机执行配置之间的比较。

修复在原runtime组合入口加入 `assertExecutionBinding(manifest,c.binding,transport.binding)`，由原current/admit共同调用。authority对同一manifest的验签、manifestHash和binding完整比较原样保留，所以任何执行必须同时满足签名批准=manifest=当前配置=实际transport。随后原平台whoami/user_info/bot info检查与该同一transport绑定核对，发送前callback再复核。

覆盖appId、tenantKey、scope、ownerId、participantId、botId、ownerChatId、participantChatId、policyVersion、resourceVersion、purpose、summaryHash、previewHash。字段必须为非空字符串，无额外字段；scope必须由tenant/app严格推导；角色与会话不能相同。完整比较拒绝“另一份不同但内部自洽”的配置，不为其重签批准。

首次登记时，运行组合检查先于authority.admit中的gate.register；失败时requests=0、effects=0、capability=2、无setting/marker，平台端口调用0。每次current、确认及beforeSend均重核。错误发生在已登记后时，只拒绝主动执行，未修改原隔离模块/activation/账本机制。

transport.binding现在是不可替换的冻结快照，controller.transport为不可替换引用，确保所检查transport就是执行用的transport。二者没有增加新权限、新服务或新发送路径。未宣称抵御同一OS用户任意改写全部程序/数据。

完整host测试见dm/tests/ready1-fix1-binding.test.mjs。原七项对应：matching-full-chain；platform tenantKey；initial tenant/bot/owner/participantChat；original signature control。除此之外逐一验证其余绑定字段、角色互换、缺字段/类型/空值/多字段、登记后签名变化、异步身份读取期间配置/批准变化、事件身份、transport替换，以及错误配置重启后UNKNOWN与被动隔离保留。

只两处旧错误码预期适配：审核七项chat对照，由仅SEND_BINDING_INVALID接受更早EXECUTION_BINDING_MISMATCH；READY1的篡改manifest对照接受新的提前错误。其他安全断言原样保留。原源码/断言/失败TAP不回写。
