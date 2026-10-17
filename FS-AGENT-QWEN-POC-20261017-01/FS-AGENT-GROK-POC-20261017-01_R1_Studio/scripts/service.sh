#!/bin/bash
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "$0")/.." && pwd)
case ${1:-help} in
  status)
    echo 'Existing AM221D221 service status; check the PoC prepare receipt before enabling routes.'
    exec /bin/zsh "$project_dir/../local-qwen3.8/feishu-bridge/service.sh" status
    ;;
  check-api)
    exec "$project_dir/.venv/bin/python" "$project_dir/scripts/check_local_qwen.py"
    ;;
  prepare)
    exec "$project_dir/.venv/bin/python" "$project_dir/scripts/prepare_existing_bridge.py"
    ;;
  *)
    echo 'Usage: service.sh status|check-api|prepare' >&2
    echo 'Use the existing bridge service controls after verified preparation; this script never starts a new consumer.' >&2
    exit 2
    ;;
esac
