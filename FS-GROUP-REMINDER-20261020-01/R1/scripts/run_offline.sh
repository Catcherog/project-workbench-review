#!/bin/sh
set -eu
cd "$(dirname "$0")/../source/fs-agent"
PYTHONPATH=src uv run --locked --group dev pytest -q tests/test_reminder.py tests/test_reminder_transport.py tests/test_reminder_bridge.py tests/test_doc_logic.py tests/test_doc_logic_fix1.py tests/test_meegle_port.py tests/test_gateway.py tests/test_post_flow.py tests/test_embedded.py tests/test_feishu_transport.py tests/test_local_api.py bridge/test_bridge.py
