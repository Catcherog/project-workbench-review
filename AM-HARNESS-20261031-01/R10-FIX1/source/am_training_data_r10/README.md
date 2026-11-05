# 本人风格合成训练候选（R10-FIX1）

从已授权、尚在保留期限内的本人发送文本归纳表达特征。`profile.py` 为每条归纳保留匿名样本标识、来源哈希与计数；空来源返回“风格依据不足”，生成器拒绝继续。来源账号不证明每条都是本人亲笔，规则归纳不冒充本人逐项确认。

`scenarios.py` 分开维护明确事实、事实陈述与标明“建议”的动作。`synthetic.py` 实际使用画像中的分段方式和请求语气生成正文。事实相同而画像不同的对照已覆盖全部20个家族。采购条件、检查点、计划完成日期、反馈期限、批准与回执保持各自含义；跟进主题缺失时澄清，提供了明确主题才生成对应预览。

默认输出2400条SFT和1200对DPO候选，按16/4个家族隔离train/dev。风格DPO的两边共享事实陈述、均为自然表达；事实边界负例另行标记。每行保留对应R10旧候选ID与事实、答案、画像哈希。2400行不是2400个独立语义场景。

```sh
python -m am_training_data_r10.synthetic --owner-messages /absolute/private/owner-messages.json --output /absolute/private/new-candidates
python -m unittest discover -s am_training_data_r10
```

输入对象包含`text`、原文SHA-256 `text_sha256`、`exclude_reasons`、`raw_expires_at_ms`。排除过期、来源哈希不符、转发、附件、命令和机器人代发，并去重。生成目录必须全新，禁止覆盖已审阅语料。

生成器不执行训练或部署。`human_approved=false`、`training_eligible=false`表示这些仍是合成候选，不能伪装成现有MLX入口要求的gold。R10-FIX1已准备32训练/8开发的首批方案及14个合成保留测试；合成保留测试不等同于新独立真人业务留出集。
