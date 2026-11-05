"""Produce a reviewable, exact-baseline patch; never modify the source tree."""
from __future__ import annotations
import argparse
import difflib
import hashlib
import json
from pathlib import Path

EXPECTED_SHA256 = "2875ccdb5756cca9eae47e9e020c37071c63f76192db4432b0a001178a70c140"


def patched(source: str) -> str:
    init = "        self.expression=NativeFollowupExpression(self)\n"
    actor = "    def actor(self,row):\n"
    begin = "            if type(request) is not dict or request.get('expires_at',0)<=self.s.clock():raise BoundaryError('FOLLOWUP_OPERATOR_EXPIRED')\n"
    end = "            result['ok']=True\n"
    queue = "        paths=sorted(self.operator_queue.glob('*.request.json'))[:1]\n"
    written = "        with os.fdopen(fd,'w') as stream:json.dump(result,stream,ensure_ascii=False)\n"
    request_init = "        result={'ok':False,'new_engineer_sends':0}\n"
    for marker in (init, actor, begin, end, queue, written, request_init):
        if source.count(marker) != 1:
            raise ValueError("HOST_PATCH_ANCHOR_CHANGED")
    source = source.replace(init, init + "        # Optional web channel: original scheduler/consumer and native approval stay authoritative.\n"
        "        from am_workbench_adapter import install_from_env\n"
        "        self.workbench=install_from_env(self)\n")
    source = source.replace(actor, actor + "        web=getattr(self,'workbench',None)\n"
        "        if web is not None and web.is_context(row):return web.actor(row)\n")
    source = source.replace(queue, "        if getattr(self,'workbench',None) is not None:self.workbench.maintenance()\n" + queue)
    source = source.replace(request_init, request_init + "        request=None\n")
    source = source.replace(written, written + "        if isinstance(request,dict) and request.get('operation')=='workbench':claim.unlink(missing_ok=True)\n")
    start = source.index(begin)
    finish = source.index(end, start)
    legacy = source[start + len(begin):finish]
    branch = (
        "            if type(request) is not dict:raise BoundaryError('FOLLOWUP_OPERATOR_EXPIRED')\n"
        "            if request.get('operation')=='workbench':\n"
        "                if self.workbench is None:raise BoundaryError('WORKBENCH_NOT_ENABLED')\n"
        "                result['workbench']=self.workbench.handle(request.get('envelope'))\n"
        "            else:\n"
        "                if request.get('expires_at',0)<=self.s.clock():raise BoundaryError('FOLLOWUP_OPERATOR_EXPIRED')\n"
        + "".join("    " + line if line.strip() else line for line in legacy.splitlines(keepends=True))
    )
    result = source[:start] + branch + source[finish:]
    compile(result, "am_followup_host.py", "exec")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    data = args.source.read_bytes()
    checksum = hashlib.sha256(data).hexdigest()
    if checksum != EXPECTED_SHA256:
        raise SystemExit("HOST_BASELINE_CHANGED: inspect the current host and regenerate an exact patch; no files changed")
    source = data.decode("utf-8")
    result = patched(source)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "am_followup_host.py").write_text(result, encoding="utf-8")
    delta = "".join(difflib.unified_diff(source.splitlines(keepends=True), result.splitlines(keepends=True),
        fromfile="a/local-qwen3.8/feishu-bridge/am_followup_host.py",
        tofile="b/local-qwen3.8/feishu-bridge/am_followup_host.py"))
    (args.output_dir / "am_followup_host.patch").write_text(delta, encoding="utf-8")
    report = {"reviewRef": "777921b15c7a2ad19d2bec8591ffad29d4daa9d2",
              "reportedRuntimeSourceCommit": "4e46d18c45951a02f27ae47acc107fbf34f8cbec",
              "beforeSha256": checksum, "afterSha256": hashlib.sha256(result.encode()).hexdigest(),
              "sourceModified": False, "newConsumer": False, "defaultEnabled": False}
    (args.output_dir / "patch-manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
