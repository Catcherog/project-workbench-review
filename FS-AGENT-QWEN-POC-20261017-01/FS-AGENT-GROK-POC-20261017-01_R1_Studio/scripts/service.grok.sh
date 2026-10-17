#!/bin/bash
set -euo pipefail
runtime_python=/Library/FSAgentGrok/app/.venv/bin/python
config_path=/Library/FSAgentGrok/config/environment.json
case ${1:-help} in
  start) sudo /bin/launchctl bootstrap system /Library/LaunchDaemons/com.fsagent.grokpoc.plist ;;
  stop) sudo /bin/launchctl bootout system/com.fsagent.grokpoc ;;
  status) sudo /bin/launchctl print system/com.fsagent.grokpoc ;;
  doctor|probe|login|p1|resume|configure)
    sudo -u _fsagent /usr/bin/env -i HOME=/Library/FSAgentGrok/home PATH=/usr/bin:/bin:/usr/sbin:/sbin \
      "$runtime_python" -m fs_agent.cli "$1" --config "$config_path" ;;
  *) echo 'Usage: service.sh doctor|configure|probe|login|p1|start|status|stop|resume'; exit 2 ;;
esac
