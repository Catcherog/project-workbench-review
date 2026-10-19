#!/bin/sh
set -eu
cd "$(dirname "$0")/../source/fs-agent"
PYTHONPATH=src "${PYTHON:-python3}" -m pytest -q tests/test_doc_logic.py tests/test_gateway.py tests/test_post_flow.py tests/test_embedded.py tests/test_feishu_transport.py ../local-qwen3.8/feishu-bridge/test_bridge.py
