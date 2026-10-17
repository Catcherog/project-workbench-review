#!/usr/bin/env python3
"""One real synthetic API check. Does not install a service, connect Feishu or read credentials."""
import json
import time
from pathlib import Path

from fs_agent.config import BoundaryError
from fs_agent.local_api import LocalQwenClient


def main():
    path = Path(__file__).resolve().parents[1] / "config" / "environment.example.json"
    settings = json.loads(path.read_text())["provider"]
    client = LocalQwenClient(settings["base_url"], settings["model"], settings["model_digest"])
    started = time.monotonic()
    receipt = client.fingerprint()
    answer = client.complete("合成验证：2+3 等于多少？只回复数字 5，不使用工具。", timeout=120)
    if answer != "5":
        raise BoundaryError("P1_SYNTHETIC_ASSERTION_FAILED")
    receipt.update(real_api_success=True, synthetic_result="5", elapsed=time.monotonic()-started,
                   completed_at=time.time(), feishu_test=False, dedicated_service_test=False)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except BoundaryError as exc:
        print(json.dumps({"error":str(exc)}))
        raise SystemExit(2)
