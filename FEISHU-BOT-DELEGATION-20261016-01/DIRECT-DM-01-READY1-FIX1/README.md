# DIRECT-DM-01-READY1-FIX1

只修READY1-B01，入口00_当前交接.md。原七项反例4/3→7/7；完整DM138/138，事件桥5/5。R1/FIX3继承原34/34、84/84，本轮不冒称复跑或GPT审核。

`node tools/build-manifest.mjs` 后 `python3 tools/verify-ready1-fix1.py`。Node>=22.13、parse5 8.0.1。所有测试显式隔离；不要默认启动local-http.mjs。reviewer-repro是审核shim，禁止安装。

用户对原正文/安装影响及有界测试发送的批准保留；仍停在待增量独立复审和真实前置证据。未安装、重启、导入生产信任、真实登记或发送。
