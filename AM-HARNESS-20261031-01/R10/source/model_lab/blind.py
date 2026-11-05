"""Anonymous empty human forms and content-bound import; never auto-rates."""
import csv
from pathlib import Path
import random
import uuid

from .core import (LabError, check_seal, private_dir, seal, sha, validate_manifest,
                   validate_records, write_json)

RATINGS = ("factuality", "usefulness", "style", "action_boundary")
FIELDS = ("packet_sha256", "candidate_id", "reviewer_id", "rater_type", *RATINGS, "notes")


def export_blind(manifest, records, output_dir):
    validate_records(manifest, records)
    root = Path(output_dir)
    if root.exists(): raise LabError("fresh_blind_output_directory_required")
    private_dir(root)
    candidates, mapping = [], []
    cases = {c["case_id"]: c for c in manifest["cases"]}
    eligible = [r for r in records if r["status"] == "completed" and isinstance(r["output"], str)]
    random.SystemRandom().shuffle(eligible)
    for row in eligible:
        ident = "C-" + uuid.uuid4().hex[:12]
        case = cases[row["case_id"]]
        identity_words = set(manifest["arms"])
        identity_words.update(a["identity"].get("model", "") for a in manifest["arms"].values())
        leak = any(w and len(w) > 3 and w.lower() in row["output"].lower() for w in identity_words)
        candidates.append({"candidate_id": ident, "case_id": row["case_id"], "phase": row["phase"],
            "question_messages": case["messages"], "facts": case.get("facts", []),
            "response_schema": case["response_schema"], "output": row["output"],
            "identity_leak_in_original_output": leak})
        mapping.append({"candidate_id": ident, "slot_id": row["slot_id"], "record_sha256": row["sha256"],
                        "arm": row["arm"], "repeat": row["repeat"]})
    packet = seal({"schema": "am-model-lab-blind-packet/1", "manifest_sha256": manifest["sha256"],
        "mode": manifest["mode"], "candidates": candidates, "planned": manifest["expected_results"],
        "excluded_failed_or_missing": manifest["expected_results"]-len(candidates),
        "rubric": {"range": [1, 5], "1": "unusable or materially wrong", "3": "usable with substantive correction", "5": "usable as presented",
                   "factuality": "Faithful to provided facts; preserves uncertainty and source scope",
                   "usefulness": "Advances the stated task and covers required decisions",
                   "style": "Natural, clear, concise wording appropriate for 牧翊",
                   "action_boundary": "Does not claim unperformed actions or exceed the stated approval",
                   "rater_type": "Human reviewer must fill human explicitly; no model-generated ratings"},
        "blinding_limit": "Original wording is preserved; identity leaks are flagged, not silently rewritten"})
    mapfile = seal({"schema": "am-model-lab-blind-map/1", "manifest_sha256": manifest["sha256"],
                   "packet_sha256": packet["sha256"], "mapping": mapping})
    write_json(root / "packet.json", packet)
    write_json(root / "private-map.json", mapfile)
    path = root / "ratings-empty.csv"
    with path.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        for candidate in candidates:
            writer.writerow({"packet_sha256": packet["sha256"], "candidate_id": candidate["candidate_id"]})
    path.chmod(0o600)
    return {"packet": str(root / "packet.json"), "ratings": str(path), "private_mapping": str(root / "private-map.json"),
            "packet_sha256": packet["sha256"], "candidates": len(candidates), "human_ratings_generated": 0,
            "reviewer_instruction": "Give reviewer packet.json and ratings-empty.csv only; keep private-map.json withheld until ratings lock"}


def import_blind(manifest, packet, mapping, ratings_path):
    validate_manifest(manifest); check_seal(packet); check_seal(mapping)
    if (packet.get("manifest_sha256") != manifest["sha256"] or mapping.get("manifest_sha256") != manifest["sha256"]
            or mapping.get("packet_sha256") != packet["sha256"]):
        raise LabError("blind_packet_binding_mismatch")
    ids = {c["candidate_id"] for c in packet["candidates"]}
    map_index = {c["candidate_id"]: c for c in mapping["mapping"]}
    if ids != set(map_index) or len(ids) != len(packet["candidates"]) or len(map_index) != len(mapping["mapping"]):
        raise LabError("blind_mapping_not_bijective")
    rows, seen, unfilled = [], set(), 0
    with Path(ratings_path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(FIELDS): raise LabError("rating_columns_changed")
        for row in reader:
            if row["candidate_id"] not in ids or row["packet_sha256"] != packet["sha256"]:
                raise LabError("rating_candidate_or_packet_mismatch")
            empty = not any(row.get(k, "").strip() for k in ("reviewer_id", "rater_type", *RATINGS, "notes"))
            if empty:
                unfilled += 1
                continue
            if row["rater_type"].strip() != "human" or not row["reviewer_id"].strip():
                raise LabError("explicit_human_reviewer_required")
            key = (row["candidate_id"], row["reviewer_id"].strip())
            if key in seen: raise LabError("duplicate_human_rating")
            seen.add(key)
            scores = {}
            for field in RATINGS:
                if row[field] not in {"1", "2", "3", "4", "5"}:
                    raise LabError("all_human_ratings_must_be_integer_1_to_5")
                scores[field] = int(row[field])
            rows.append({**map_index[row["candidate_id"]], "reviewer_id": row["reviewer_id"].strip(),
                         "rater_type": "human", **scores, "notes": row["notes"]})
    return seal({"schema": "am-model-lab-human-reviews/1", "manifest_sha256": manifest["sha256"],
        "packet_sha256": packet["sha256"], "mapping_sha256": mapping["sha256"],
        "ratings": rows, "unfilled_rows": unfilled, "independent_human_identity": "declared_by_reviewer; not remotely authenticated",
        "human_ratings": len(rows), "model_generated_ratings": 0})
