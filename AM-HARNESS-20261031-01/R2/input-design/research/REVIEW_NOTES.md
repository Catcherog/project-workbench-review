# 定向设计复核收口

本包主报告是统一的最终设计入口；其余研究记录保留独立阅读和复核范围，不生成第二个实施基线。

`current_baseline_review.md` 是 FIX1 定向静态核对。`reference_review.md` 记录早期 22 项参考合同阶段的同行审查，已指出并修复工作单元/receipt/gap 完整性和保护块顺序。

之后根审查又补充 durable expression 的真实 RunBinding、脏 intent 类型和 SCHEDULE 枚举三个点。最终打包副本完整运行 26 项，记录在 `../VALIDATION.md` 与 `../reference_checks.txt`。旧记录中的 22 项不与后来的 26 项累计。

源码索引中的原本机相对目录仅用于说明研究时文件身份；执行方按其中 `review_path` 与固定 GitHub URL 取得所需源码，不要求在用户机器创建相同 scratch 目录。

官方资料归因仅采用官网、官方文档和由官网确认的官方 GitHub 仓库。社区镜像未作为框架能力依据。研究没有执行 OpenAI/DeepSeek API，也不比较未经本业务测试的模型优劣。

