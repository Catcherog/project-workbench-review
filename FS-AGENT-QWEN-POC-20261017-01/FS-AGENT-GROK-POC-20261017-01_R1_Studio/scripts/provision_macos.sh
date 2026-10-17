#!/bin/bash
# Administrator-run setup only. Creates a dedicated account; does not start a consumer.
set -euo pipefail
echo 'This Grok installer is retired after the switch to the existing local Qwen API. No changes made.' >&2
exit 2
if [[ $(id -u) -ne 0 ]]; then
  echo 'Run this script with sudo; the administrator enters the password locally.' >&2
  exit 2
fi
project_dir=$(cd "$(dirname "$0")/.." && pwd)
service_root=/Library/FSAgentGrok
service_user=_fsagent
uv_source=${1:?Provide the absolute path to the uv executable as argument 1}
[[ -x "$uv_source" && "$uv_source" = /* ]]
[[ -f "$project_dir/.vendor/grok-1.0.62/grok" ]]
[[ -f "$project_dir/.vendor/grok-1.0.62/release.json" ]]
/usr/bin/python3 - "$project_dir/.vendor/grok-1.0.62" <<'PY'
import hashlib,json,pathlib,sys
p=pathlib.Path(sys.argv[1]); r=json.loads((p/'release.json').read_text())
assert r['publisher']=='@xai-official' and r['package_version']=='1.0.62'
assert r['package_name']=='@xai-official/grok-darwin-arm64'
assert hashlib.sha256((p/'grok').read_bytes()).hexdigest()==r['binary_sha256']
print('Official staged binary hash verified; preparing the dedicated service account.')
PY
if /usr/bin/dscl . -read "/Users/$service_user" >/dev/null 2>&1; then
  existing_home=$(/usr/bin/dscl . -read "/Users/$service_user" NFSHomeDirectory)
  [[ "$existing_home" = "NFSHomeDirectory: $service_root/home" ]] || { echo 'Existing account has another home; no changes made.' >&2; exit 2; }
else
  [[ ! -e "$service_root" ]] || { echo 'Unmanaged service directory already exists; no changes made.' >&2; exit 2; }
  if /usr/bin/dscl . -read "/Groups/$service_user" >/dev/null 2>&1; then
    echo 'A matching group already exists without the service account; review it first.' >&2
    exit 2
  fi
  account_id=450
  used_ids=$(/usr/bin/dscl . -list /Users UniqueID; /usr/bin/dscl . -list /Groups PrimaryGroupID)
  while /usr/bin/awk '{print $NF}' <<< "$used_ids" | /usr/bin/grep -qx "$account_id"; do
    account_id=$((account_id + 1))
    [[ $account_id -lt 500 ]] || { echo 'No unused system account ID found.' >&2; exit 2; }
  done
  /usr/bin/dscl . -create "/Groups/$service_user"
  /usr/bin/dscl . -create "/Groups/$service_user" PrimaryGroupID "$account_id"
  /usr/bin/dscl . -create "/Users/$service_user"
  /usr/bin/dscl . -create "/Users/$service_user" UniqueID "$account_id"
  /usr/bin/dscl . -create "/Users/$service_user" PrimaryGroupID "$account_id"
  /usr/bin/dscl . -create "/Users/$service_user" NFSHomeDirectory "$service_root/home"
  /usr/bin/dscl . -create "/Users/$service_user" UserShell /usr/bin/false
  /usr/bin/dscl . -create "/Users/$service_user" RealName 'Feishu Grok PoC Service'
  /usr/bin/dscl . -create "/Users/$service_user" Password '*'
  /usr/bin/dscl . -create "/Users/$service_user" IsHidden 1
fi
for path in "$service_root" "$service_root/home" "$service_root/state" "$service_root/tasks" "$service_root/artifacts" "$service_root/secrets" "$service_root/config" "$service_root/cache" "$service_root/python" "$service_root/app" "$service_root/bin"; do
  /usr/bin/install -d -m 700 -o "$service_user" -g "$service_user" "$path"
done
[[ ! -e "$service_root/state/instance.lock" ]] || { echo 'Existing runtime detected. Stop and review it before redeploying.' >&2; exit 2; }
/usr/bin/install -m 755 "$uv_source" "$service_root/bin/uv"
/usr/bin/install -m 755 "$project_dir/.vendor/grok-1.0.62/grok" "$service_root/bin/grok"
/usr/bin/install -m 644 "$project_dir/.vendor/grok-1.0.62/release.json" "$service_root/bin/release.json"
for item in pyproject.toml uv.lock .python-version; do
  /usr/bin/install -m 600 -o "$service_user" -g "$service_user" "$project_dir/$item" "$service_root/app/$item"
done
/bin/cp -R "$project_dir/src" "$service_root/app/"
/usr/sbin/chown -R "$service_user:$service_user" "$service_root/app"
if [[ ! -e "$service_root/config/environment.json" ]]; then
  /usr/bin/install -m 600 -o "$service_user" -g "$service_user" "$project_dir/config/environment.example.json" "$service_root/config/environment.json"
fi
/usr/bin/sudo -u "$service_user" /usr/bin/env -i HOME="$service_root/home" PATH=/usr/bin:/bin:/usr/sbin:/sbin UV_PYTHON_INSTALL_DIR="$service_root/python" UV_CACHE_DIR="$service_root/cache" \
  "$service_root/bin/uv" --no-config sync --frozen --no-dev --project "$service_root/app" --python 3.12.13 --python-preference only-managed
/usr/bin/install -m 644 "$project_dir/config/com.fsagent.grokpoc.plist" /Library/LaunchDaemons/com.fsagent.grokpoc.plist
/usr/bin/sudo -u "$service_user" /usr/bin/env -i HOME="$service_root/home" PATH=/usr/bin:/bin:/usr/sbin:/sbin \
  "$service_root/app/.venv/bin/python" -m fs_agent.cli probe --config "$service_root/config/environment.json"
echo 'Prepared dedicated account, Python and CLI. Fill private configuration, run P1, then start the service. No consumer was started.'
