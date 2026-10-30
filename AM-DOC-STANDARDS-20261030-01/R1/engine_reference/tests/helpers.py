import json
from pathlib import Path

from am_doc_engine.models import AccessContext, DraftRequest, profile_from_dict, snapshot_from_dict


def demo(kind="charter"):
    raw = json.loads((Path(__file__).parents[1] / "examples" / "demo_bundle.json").read_text(encoding="utf-8"))
    profile = next(profile_from_dict(v) for v in raw["profiles"] if v["doc_type"] == kind)
    request = next(DraftRequest(**v) for v in raw["requests"] if v["doc_type"] == kind)
    a = raw["access"]
    access = AccessContext(a["tenant_id"], a["actor_id"], tuple(a["project_ids"]), tuple(a["scopes"]), a["app_id"], a["chat_id"])
    return profile, request, access, snapshot_from_dict(raw["snapshot"])
