#!/bin/zsh
set -eu
label='local.qwen.feishu'
domain="gui/$(id -u)"
plist="$HOME/Library/LaunchAgents/$label.plist"
case "${1:-status}" in
  start)
    if ! launchctl print "$domain/$label" >/dev/null 2>&1; then
      launchctl bootstrap "$domain" "$plist"
    fi
    ;;
  stop) launchctl bootout "$domain/$label" ;;
  restart) launchctl kickstart -k "$domain/$label" ;;
  status)
    launchctl print "$domain/$label"
    for file in "$HOME/.local/share/local-qwen-feishu/state/"*-status.json; do
      [[ -f "$file" ]] && cat "$file"
    done
    ;;
  *) print -u2 '用法：service.sh start|stop|restart|status'; exit 2 ;;
esac
