#!/usr/bin/env python3
"""Verify approved contact fields, then prepare (optionally activate) the same bridge.

No new consumer, service restart or Feishu message is created by this command.
"""
import argparse
from dataclasses import replace
import json
import logging
import os
from pathlib import Path
import sqlite3
import time

from lark_oapi.api.contact.v3 import GetUserRequest

from fs_agent.config import BoundaryError, Config
from fs_agent.feishu import Feishu
from fs_agent.provider import atomic_json
from fs_agent.qwen_provider import LocalQwenProvider


def prepare(activate=False):
    private = Path.home() / ".local/share/local-qwen-feishu"
    path = private / "poc/config/environment.json"
    config = Config.load(path, provider_setup=True)
    config.check_service()
    original = json.loads((private / "config.json").read_text())
    if (config.runtime_mode != "existing_login" or config.event_transport != "existing_bridge"
            or original["app_id"] != config.app_id or not original.get("exclusive_consumer_confirmed")
            or Path(original["app_secret_file"]) != config.app_secret_file):
        raise BoundaryError("EXISTING_BRIDGE_CONFIG_INVALID")
    if len(config.users) != 2 or len(set(config.users)) != 2 or config.owner not in config.users:
        raise BoundaryError("EXACT_TWO_USERS_REQUIRED")
    api = Feishu(config)
    departments = set()
    for user_id in config.users:
        request = (GetUserRequest.builder().user_id(user_id).user_id_type("open_id")
                   .department_id_type("open_department_id").build())
        response = api.client.contact.v3.user.get(request)
        if not response.success() or not response.data or not response.data.user:
            raise BoundaryError("TEST_USER_LOOKUP_FAILED")
        user = response.data.user
        if user.open_id != user_id:
            raise BoundaryError("TEST_USER_ID_MISMATCH")
        if not user.status or not user.department_ids:
            raise BoundaryError("CONTACT_PERMISSIONS_NOT_EFFECTIVE")
        if user.status.is_activated is not True or any(
                getattr(user.status, key, False) for key in ("is_resigned", "is_frozen", "is_exited")):
            raise BoundaryError("TEST_USER_NOT_ACTIVE")
        if not all(isinstance(d, str) and d for d in user.department_ids):
            raise BoundaryError("TEST_DEPARTMENT_INVALID")
        departments.update(user.department_ids)
    checked = replace(config, departments=tuple(sorted(departments)), department_match="any_exact",
                      exclusive_consumer=True)
    checked.check_feishu()
    LocalQwenProvider(checked).pin()
    data = json.loads(path.read_text())
    data["template_only"] = False
    data["feishu"].update(allowed_department_ids=list(checked.departments), department_match="any_exact",
                          exclusive_test_consumer_confirmed=True)
    receipt = {"checked_at":time.time(), "verified_users":2, "department_count":len(departments),
               "department_policy":"exact current departments plus two-user allowlist",
               "contact_fields_verified":True, "new_consumer_started":False,
               "service_restarted":False, "activation_configured":activate}
    if activate:
        uri = "file:" + str(Path(original["state_directory"]) / "chat.sqlite3") + "?mode=ro"
        with sqlite3.connect(uri, uri=True) as db:
            busy = db.execute("SELECT COUNT(*) FROM inbox WHERE state IN ('queued','processing','sending')").fetchone()[0]
        if busy:
            raise BoundaryError("EXISTING_BRIDGE_BUSY")
        backup = private / "config.before-poc.json"
        if not backup.exists():
            atomic_json(backup, original)
        original["poc_config"] = str(path)
        original["poc_configuration_authorization"] = "User approved existing AM221D221 service and login account, 2026-10-17."
    atomic_json(path, data)
    if activate:
        atomic_json(private / "config.json", original)
    atomic_json(config.root / "state/prepare-receipt.json", receipt)
    return receipt


if __name__ == "__main__":
    os.umask(0o077)
    logging.disable(logging.CRITICAL)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--activate", action="store_true", help="Add PoC to the existing bridge config; does not restart it")
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.activate), ensure_ascii=False, indent=2))
    except BoundaryError as exc:
        print(json.dumps({"ready":False, "error":str(exc)}))
        raise SystemExit(2)
    except Exception as exc:
        print(json.dumps({"ready":False, "error":"PREPARE_FAILED", "type":type(exc).__name__}))
        raise SystemExit(3)
