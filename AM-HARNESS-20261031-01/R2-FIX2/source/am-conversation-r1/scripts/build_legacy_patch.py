#!/usr/bin/env python3
"""Build a reviewable overlay/patch against the verified AM UX3 snapshot.

This script never modifies the reference checkout or a running installation.
Input hashes must match both known files before any output is written.  A newer
Studio checkout requires a deliberate rebase by Codex, not forced replacement.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
from pathlib import Path
import py_compile
import tempfile


BASE_COMMIT = "4cae29d3b33ae04885038c2f52cdd425182b9f1a"
EXPECTED = {
    "local-qwen3.8/feishu-bridge/am_service.py": "8b72a6cead624bad897570c2ce61b702d2d7e48c30d907c45e356f41bec9ed2e",
    "local-qwen3.8/feishu-bridge/bridge.py": "ac7d211cdff53c48feb60b248afed2bba1827e2836a2463a35b3a12c733b2b80",
}


def replace_once(text: str, before: str, after: str) -> str:
    if text.count(before) != 1:
        raise ValueError("PATCH_ANCHOR_MISMATCH")
    return text.replace(before, after, 1)


def patch_service(text: str) -> str:
    text = replace_once(text,
        "execution_policy=None,query_settings=None):",
        "execution_policy=None,query_settings=None,conversation_settings=None):")
    text = replace_once(text,
        "        self.init_query(query_settings)\n        gateway.am_self=self\n",
        "        self.init_query(query_settings)\n"
        "        self.conversation=None\n"
        "        if conversation_settings is not None:\n"
        "            if not isinstance(conversation_settings,dict) or type(conversation_settings.get('enabled',False)) is not bool:\n"
        "                raise BoundaryError('AM_CONVERSATION_SETTINGS_INVALID')\n"
        "            if conversation_settings.get('enabled'):\n"
        "                from am_conversation.legacy import LegacyConversationBridge\n"
        "                self.conversation=LegacyConversationBridge(self,conversation_settings)\n"
        "        gateway.am_self=self\n")
    text = replace_once(text,
        "    def wants(self,text):\n",
        "    def wants(self,text):\n"
        "        if self.conversation is not None and self.conversation.wants(text):return True\n")
    text = replace_once(text,
        "'kind':'collection' if collection else 'text',",
        "'kind':'collection' if collection else 'conversation' if self.conversation is not None and self.conversation.wants(text) else 'text',")
    text = replace_once(text,
        "    def delivered(self,c,row,message_id):\n",
        "    def delivered(self,c,row,message_id):\n"
        "        if self.conversation is not None:\n"
        "            # A failed preview acknowledgement must not invalidate a verified send.\n"
        "            try:self.conversation.delivered(row,message_id,conn=c)\n"
        "            except Exception:pass\n")
    text = replace_once(text,
        "        try:\n            row['_readonly_request']=self.readonly_request(row)\n",
        "        try:\n"
        "            if row.get('kind')=='conversation':\n"
        "                if self.conversation is None:raise BoundaryError('CONVERSATION_DISABLED')\n"
        "                self.conversation.process(row)\n"
        "                self.s.execute(\"UPDATE am_inbox SET state='done' WHERE id=?\",(row['id'],))\n"
        "                return True\n"
        "            row['_readonly_request']=self.readonly_request(row)\n")
    text = replace_once(text,
        "            if row.get('_feedback_context'):\n",
        "            if row.get('kind')=='conversation':\n"
        "                # Data-free recovery uses the original denial-delivery binding.\n"
        "                self.notify(dict(row,_query_read=False,_query_denial=True),\n"
        "                    text='当前未能处理这条消息。请稍后重试，或联系管理员核对访问范围。',\n"
        "                    kind='conversation_error',event_key='conversation-error:'+row['id'])\n"
        "            elif row.get('_feedback_context'):\n")
    return text


def patch_bridge(text: str) -> str:
    text = replace_once(text,
        "execution_policy=config.get('am_write_execution'),query_settings=config.get('am_query'))",
        "execution_policy=config.get('am_write_execution'),query_settings=config.get('am_query'),\n"
        "                                        conversation_settings=config.get('am_conversation'))")
    text = replace_once(text,
        "            bridge.am_self.close_query()\n",
        "            bridge.am_self.close_query()\n"
        "            if bridge.am_self.conversation is not None:bridge.am_self.conversation.close()\n")
    return text


def build(reference_root: Path, output_dir: Path) -> dict:
    reference_root, output_dir = Path(reference_root), Path(output_dir)
    originals: dict[str, str] = {}
    # Validate every input before creating output directories or partial files.
    for relative, expected in EXPECTED.items():
        raw = (reference_root / relative).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("BASELINE_SHA256_MISMATCH:" + relative)
        originals[relative] = raw.decode("utf-8")
    modified = {
        "local-qwen3.8/feishu-bridge/am_service.py": patch_service(originals["local-qwen3.8/feishu-bridge/am_service.py"]),
        "local-qwen3.8/feishu-bridge/bridge.py": patch_bridge(originals["local-qwen3.8/feishu-bridge/bridge.py"]),
    }
    for relative, text in modified.items():
        compile(text, relative, "exec")
    patch_parts = []
    entries = []
    for relative, text in modified.items():
        destination = output_dir / "overlay" / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
        patch_parts.extend(difflib.unified_diff(originals[relative].splitlines(keepends=True),
            text.splitlines(keepends=True), fromfile="a/" + relative, tofile="b/" + relative))
        entries.append({"path": relative, "base_sha256": EXPECTED[relative],
                        "overlay_sha256": hashlib.sha256(text.encode()).hexdigest()})
    output_dir.mkdir(parents=True, exist_ok=True)
    patch_path = output_dir / "legacy-am-conversation.patch"
    patch_path.write_text("".join(patch_parts), encoding="utf-8")
    with tempfile.TemporaryDirectory(prefix="am-conversation-compile-") as temporary:
        for index, relative in enumerate(modified):
            py_compile.compile(str(output_dir / "overlay" / relative),
                               cfile=str(Path(temporary) / f"{index}.pyc"), doraise=True)
    manifest = {"base_repository": "Catcherog/project-workbench-review", "base_commit": BASE_COMMIT,
                "changed_files": entries, "patch": patch_path.name,
                "patch_sha256": hashlib.sha256(patch_path.read_bytes()).hexdigest(),
                "python_compile": "passed", "runtime_integration": "not_executed",
                "production_enabled": False,
                "note": "Install the am_conversation package alongside the original fs_agent environment; review/rebase before applying to newer source."}
    (output_dir / "MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-root", type=Path, default=root.parent / "reference_am")
    parser.add_argument("--output-dir", type=Path, default=root / "integration")
    args = parser.parse_args()
    manifest = build(args.reference_root, args.output_dir)
    print(json.dumps({"base_commit": manifest["base_commit"], "files": len(manifest["changed_files"]),
                      "python_compile": manifest["python_compile"], "output_dir": str(args.output_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
