"""Scoped Meegle CLI adapter. Exact targets are bound by the service, never by model text."""
from __future__ import annotations
import fcntl
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from .config import BoundaryError
from .doc_logic import digest, read_source, MAX_BYTES

class MeeglePort:
    def __init__(self, gateway, settings):
        self.g, self.s, self.c = gateway, gateway.store, gateway.config
        self.settings = settings
        self.binary = Path(settings["executable"])
        if (self.binary.is_symlink() or not self.binary.resolve().is_relative_to(self.c.root / "bin")
                or digest(self.binary.read_bytes()) != settings["sha256"]):
            raise BoundaryError("BUSINESS_EXECUTABLE_UNVERIFIED")
        if settings["profile"] != "fs-doc-logic-r1" or settings["allowed_user"] != self.c.owner:
            raise BoundaryError("BUSINESS_IDENTITY_BINDING_INVALID")
        self.tmp = self.c.root / "state" / "business-tmp"
        self.tmp.mkdir(mode=0o700, exist_ok=True)
        if self.tmp.is_symlink():
            raise BoundaryError("BUSINESS_DIRECTORY_INVALID")

    def _run(self, args, *, params=None, json_result=True):
        env = {k:v for k,v in os.environ.items() if not k.startswith("MEEGLE_")}
        env.update(MEEGLE_HOST="project.feishu.cn", MEEGLE_TELEMETRY="disabled",
                   MEEGLE_AI_HANDOFF="disabled", MEEGLE_NO_UPDATE_CHECK="1")
        command = [str(self.binary), *args, "--profile", self.settings["profile"], "--format", "json"]
        with tempfile.TemporaryDirectory(dir=self.tmp) as tmp:
            if params is not None:
                path = Path(tmp) / "params.json"
                path.write_text(json.dumps(params, ensure_ascii=False)); path.chmod(0o600)
                command += ["--params", "@" + str(path)]
            try:
                result = subprocess.run(command, env=env, capture_output=True, timeout=40)
            except (OSError, subprocess.TimeoutExpired):
                raise BoundaryError("BUSINESS_CALL_UNCERTAIN") from None
        if result.returncode:
            raise BoundaryError("BUSINESS_CALL_FAILED")
        if not json_result:
            return None
        if len(result.stdout) > 4_000_000:
            raise BoundaryError("BUSINESS_RESPONSE_LIMIT")
        try:
            value = json.loads(result.stdout)
        except ValueError:
            raise BoundaryError("BUSINESS_RESPONSE_INVALID") from None
        if not isinstance(value, dict) or value.get("error"):
            raise BoundaryError("BUSINESS_RESPONSE_INVALID")
        return value

    def _authorize(self, principal, alias):
        # Local actor and target filter always precede a request to the project platform.
        if (principal["user"] != self.settings["allowed_user"]
                or alias not in self.settings["targets"] or not self.g.authorized(principal)):
            raise BoundaryError("BUSINESS_SCOPE_DENIED")
        identity = self._run(["user", "me"])
        if identity.get("user_key") != self.settings["user_key"]:
            raise BoundaryError("BUSINESS_IDENTITY_CHANGED")
        return self.settings["targets"][alias]

    @staticmethod
    def _fields(data):
        fields = data.get("work_item_fields")
        if not isinstance(fields, list):
            raise BoundaryError("BUSINESS_FIELDS_INVALID")
        return {f["key"]:f.get("value") for f in fields if isinstance(f,dict) and "key" in f}

    @staticmethod
    def _files(raw):
        if isinstance(raw, str):
            try: raw = json.loads(raw)
            except ValueError: raise BoundaryError("BUSINESS_FILES_INVALID") from None
        if raw is None:
            return None
        if not isinstance(raw, list) or len(raw) > 50 or any(not isinstance(f,dict) for f in raw):
            raise BoundaryError("BUSINESS_FILES_INVALID")
        return raw

    def _state(self, principal, alias):
        b = self._authorize(principal, alias)
        node = self._run(["workflow","get-node","--project-key",b["space"],
                          "--work-item-id",b["project"],"--node-id-list",b["node"],"--need-sub-task"])
        nodes = node.get("list", [])
        if (len(nodes) != 1 or nodes[0].get("basic",{}).get("node_key") != b["node"]
                or node.get("pagination",{}).get("has_more")):
            raise BoundaryError("BUSINESS_NODE_UNVERIFIED")
        members = [str(i) for group in nodes[0].get("sub_workitems",[]) for i in group.get("workitems",[])]
        if b["deliverable"] not in members:
            raise BoundaryError("BUSINESS_PARENT_CHANGED")
        keys = [b["attachment_field"],b["approval_field"],b["node_field"],b["project_field"],
                b["document_field"],b["delivery_mode_field"],"updated_at"]
        item = self._run(["workitem","get","--project-key",b["space"],"--work-item-id",b["deliverable"],
                          "--fields",",".join(keys)])
        attr, fields = item.get("work_item_attribute",{}), self._fields(item)
        if (str(attr.get("work_item_id")) != b["deliverable"]
                or attr.get("owned_project",{}).get("key") != b["space"]
                or attr.get("work_item_type",{}).get("key") != b["type"]
                or str((fields.get(b["project_field"]) or {}).get("id")) != b["project"]
                or fields.get(b["node_field"]) != b["node"]):
            raise BoundaryError("BUSINESS_TARGET_CHANGED")
        snapshot = {"id":attr["work_item_id"], "type":attr["work_item_type"]["key"],
                    "name":attr.get("work_item_name"), "update_time":attr.get("update_time"),
                    "status":attr.get("work_item_status"), "fields":fields,
                    "node_status":nodes[0]["basic"].get("status")}
        revision = digest(json.dumps(snapshot, ensure_ascii=False, sort_keys=True))
        target = {"id":alias,"project_id":b["project"],"node_id":b["node"],"deliverable_id":b["deliverable"],
                  "revision":revision,"business_status":attr.get("work_item_status"),
                  "professional_review":fields.get(b["approval_field"]),
                  "url":b["url"]}
        return b, target, fields, self._files(fields.get(b["attachment_field"]))

    def resolve(self, principal, target_id):
        return self._state(principal, target_id)[1]

    def _download(self, b, file, destination):
        url = file.get("url") or file.get("file_url")
        if not isinstance(url,str) or not url:
            raise BoundaryError("BUSINESS_FILE_URL_MISSING")
        self._run(["attachment","+download",url,"--project-key",b["space"],
                   "--work-item-id",b["deliverable"],"--output",str(destination)], json_result=False)
        if not destination.is_file() or destination.stat().st_size > MAX_BYTES:
            raise BoundaryError("BUSINESS_FILE_LIMIT")
        return destination.read_bytes()

    def sources(self, principal, target):
        b, current, _, files = self._state(principal, target["id"])
        if current != target:
            raise BoundaryError("TARGET_REVISION_CHANGED")
        results=[]
        for n,file in enumerate(files or [],1):
            if n > 6:
                raise BoundaryError("BUSINESS_SOURCE_LIMIT")
            with tempfile.TemporaryDirectory(dir=self.tmp) as tmp:
                try:
                    size=int(file.get("size",0))
                    if size <= 0 or size > MAX_BYTES: raise BoundaryError("BUSINESS_FILE_LIMIT")
                    data=self._download(b,file,Path(tmp)/"attachment")
                    src=read_source(file.get("name","unknown"),data,source_id=f"P{n:02d}",
                                    origin=target["deliverable_id"],provenance="current_project")
                except (BoundaryError,ValueError):
                    src={"id":f"P{n:02d}","name":file.get("name","unknown"),"version":None,
                         "formed_at":None,"origin":target["deliverable_id"],"provenance":"current_project",
                         "segments":[],"read_status":"failed","limitation":"本项目已提供的关联附件暂不可读，未当作没有资料"}
                results.append(src)
        return results

    def commit(self, principal, target, content, content_hash, idem, guard):
        alias=target["id"]
        b=self._authorize(principal,alias)
        # Serialize this service's target writes. The platform API has no exposed CAS field;
        # compare again immediately before update and verify exact bytes after it.
        lockpath=self.c.root/"state"/("business-"+digest(alias)[:16]+".lock")
        with lockpath.open("a") as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            b,current,fields,files=self._state(principal,alias)
            if current != target or not guard():
                raise BoundaryError("TARGET_REVISION_CHANGED")
            approval=fields.get(b["approval_field"])
            if not isinstance(approval,dict) or approval.get("value") != b["unreviewed_value"]:
                raise BoundaryError("BUSINESS_REVIEWED_CONTENT_PROTECTED")
            if files is None:
                # Missing is not silently interpreted as empty. Only the explicitly UI-verified
                # initial empty slot at this exact fingerprint can be initialized.
                if target["revision"] != b.get("verified_empty_revision"):
                    raise BoundaryError("BUSINESS_ATTACHMENT_STATE_UNKNOWN")
                files=[]
            if len(files)>=50:
                raise BoundaryError("BUSINESS_ATTACHMENT_LIMIT")
            with tempfile.TemporaryDirectory(dir=self.tmp) as tmp:
                path=Path(tmp)/f"logic-{idem[:16]}-{content_hash[:12]}.md"
                path.write_text(content,encoding="utf-8");path.chmod(0o600)
                if digest(path.read_bytes()) != content_hash:
                    raise BoundaryError("BUSINESS_CONTENT_CHANGED")
                upload=self._run(["attachment","+upload",str(path),"--resource-type","15",
                                  "--project-key",b["space"],"--work-item-id",b["deliverable"],
                                  "--field-key",b["attachment_field"],"--content-type","text/markdown"])
                if not all(upload.get(k) for k in ("file_token","name","size","mime_type")):
                    raise BoundaryError("BUSINESS_UPLOAD_UNCERTAIN")
                self.s.execute("UPDATE logic_writes SET receipt=? WHERE idem=? AND state='unknown'",
                               (json.dumps({"phase":"uploaded","upload":upload}),idem))
                # Recheck after upload and immediately before changing the attachment field.
                _,fresh,fresh_fields,fresh_files=self._state(principal,alias)
                if fresh != target or not guard():
                    raise BoundaryError("TARGET_REVISION_CHANGED")
                previous=[]
                for f in files:
                    token=f.get("fileToken") or f.get("file_token")
                    if not token or not all(k in f for k in ("name","type","size")):
                        raise BoundaryError("BUSINESS_EXISTING_ATTACHMENT_UNVERIFIED")
                    previous.append({"name":f["name"],"type":f["type"],"size":str(f["size"]),"fileToken":token})
                new={"name":upload["name"],"type":upload["mime_type"],"size":str(upload["size"]),"fileToken":upload["file_token"]}
                self._run(["workitem","update","--project-key",b["space"],"--work-item-id",b["deliverable"]],
                          params={"fields":[{"field_key":b["attachment_field"],
                                             "field_value":json.dumps(previous+[new],ensure_ascii=False)}]},json_result=False)
                result=self.reconcile(principal,idem)
                if result is None:
                    raise BoundaryError("BUSINESS_WRITE_UNCERTAIN")
                return result

    def reconcile(self, principal, idem):
        rows=self.s.rows("SELECT * FROM logic_writes WHERE idem=?",(idem,))
        if len(rows)!=1: return None
        write=rows[0];target=json.loads(write["target"]);b,current,_,files=self._state(principal,target["id"])
        name=f"logic-{idem[:16]}-{write['content_hash'][:12]}.md"
        matches=[f for f in (files or []) if f.get("name")==name]
        if len(matches)!=1:
            return None
        file=matches[0]
        saved=json.loads(write["receipt"]) if write["receipt"] else {}
        upload=saved.get("upload",{})
        token=file.get("fileToken") or file.get("file_token")
        if not token: return None
        if not file.get("url") and not file.get("file_url") and token==upload.get("file_token"):
            file={**file,"file_url":upload.get("file_url")}
        with tempfile.TemporaryDirectory(dir=self.tmp) as tmp:
            if digest(self._download(b,file,Path(tmp)/"verify.md")) != write["content_hash"]:
                raise BoundaryError("BUSINESS_READBACK_MISMATCH")
        return {"target_id":target["id"],"content_hash":write["content_hash"],"object_id":token,"url":b["url"]}

def load_meegle_port(gateway):
    path=gateway.config.root/"config"/"document-business.json"
    if not path.exists():
        return None
    stat=path.stat()
    if path.is_symlink() or stat.st_uid!=os.getuid() or stat.st_mode & 0o077:
        raise BoundaryError("BUSINESS_CONFIG_NOT_PRIVATE")
    try:settings=json.loads(path.read_text())
    except (OSError,ValueError):raise BoundaryError("BUSINESS_CONFIG_INVALID") from None
    return MeeglePort(gateway,settings)
