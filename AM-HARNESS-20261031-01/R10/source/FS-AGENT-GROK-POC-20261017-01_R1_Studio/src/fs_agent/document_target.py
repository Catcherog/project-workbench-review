"""Strict, read-only validation of a configured Meegle document target.

Only the response shapes listed here are supported. Configuration supplies an
expectation; platform attributes, field metadata and field values must prove it.
Unknown schemas are a diagnostic, never permission to guess another target.
"""
from __future__ import annotations

import json

from .config import BoundaryError
from .doc_logic import digest
from .project_catalog import business_ids


DOCUMENT_TYPES = frozenset(("charter", "change", "closure", "test"))
DOCUMENT_NAMES = {"项目章程": "charter", "项目更改申请": "change", "项目变更申请": "change",
                  "结项报告": "closure", "项目结项报告": "closure", "测试报告": "test"}
GENERIC_DOCUMENT_LABELS = frozenset(("文档", "样机", "bom", "BOM", "评审纪要", "归档材料"))
# These are deliberately narrow adapter contracts, not claims that every Meegle
# installation uses this vocabulary. An unsupported native schema stays blocked.
FIELD_TYPES = {
    "document_kind_field": frozenset(("text", "select")),
    "document_link_field": frozenset(("file", "multi-file")),
    "project_field": frozenset(("work_item", "workitem_related_select")),
    "node_field": frozenset(("text", "select")),
    "approval_field": frozenset(("select",)),
    "delivery_mode_field": frozenset(("select",)),
}


class TargetValidationError(BoundaryError):
    """A content-free, reviewable reason why a target could not be proven."""

    def __init__(self, code, **diagnostic):
        super().__init__(code)
        self.diagnostic = diagnostic


def fingerprint(value):
    return digest(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def binding_config(value):
    if not isinstance(value, dict):
        raise TargetValidationError("BUSINESS_TARGET_CONFIG_INVALID")
    required = ("space", "project", "project_type", "project_code", "node", "deliverable", "type",
                "document_type", "document_kind_field", "document_link_field", "approval_field",
                "node_field", "project_field", "delivery_mode_field", "unreviewed_value", "url")
    missing = [key for key in required if not isinstance(value.get(key), str)
               or not value[key].strip() or value[key] != value[key].strip()]
    if missing:
        raise TargetValidationError("BUSINESS_TARGET_CONFIG_INCOMPLETE", missing_config=missing)
    if (value["document_type"] not in DOCUMENT_TYPES
            or business_ids(value["project_code"]) != [value["project_code"]]):
        raise TargetValidationError("BUSINESS_TARGET_CONFIG_INVALID", check="expected_identity")
    # Legacy aliases may agree with the new explicit fields, but never supply
    # their missing meaning and never silently override them.
    for legacy, current in (("document_field", "document_kind_field"),
                            ("attachment_field", "document_link_field")):
        if legacy in value and value[legacy] != value[current]:
            raise TargetValidationError("BUSINESS_TARGET_FIELD_CONFLICT", fields=[legacy, current])
    fields = [value[key] for key in FIELD_TYPES]
    if len(set(fields)) != len(fields):
        raise TargetValidationError("BUSINESS_TARGET_FIELD_CONFLICT", check="distinct_field_roles")
    if "project_code_field" in value and (not isinstance(value["project_code_field"], str)
            or not value["project_code_field"].strip()
            or value["project_code_field"] != value["project_code_field"].strip()):
        raise TargetValidationError("BUSINESS_TARGET_CONFIG_INVALID", check="project_code_field")
    mappings = value.get("document_type_bindings", {})
    if not isinstance(mappings, dict) or any(not isinstance(k, str) or not k or not isinstance(v, str) or v not in DOCUMENT_TYPES
                                           for k, v in mappings.items()):
        raise TargetValidationError("BUSINESS_TARGET_CONFIG_INVALID", check="document_type_bindings")
    return dict(value, attachment_field=value["document_link_field"])


def _scalar(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or str(value) == "":
        return None
    return str(value)


def _definitions(value):
    # The existing metadata reader allows grouped field definitions. A field
    # row itself is a leaf; do not mistake its options for more field rows.
    if isinstance(value, dict):
        if "field_key" in value:
            yield value
        else:
            for item in value.values():
                yield from _definitions(item)
    elif isinstance(value, list):
        for item in value:
            yield from _definitions(item)


def validate_metadata(binding, rows):
    wanted = {binding[role]: role for role in FIELD_TYPES}
    found = {}
    for field in _definitions(rows):
        key = field.get("field_key")
        if not isinstance(key, str) or key not in wanted:
            continue
        if key in found:
            raise TargetValidationError("BUSINESS_FIELD_METADATA_AMBIGUOUS", field_key=key)
        found[key] = field
    missing = sorted(set(wanted) - set(found))
    if missing:
        raise TargetValidationError("BUSINESS_FIELD_METADATA_MISSING", missing_fields=missing)
    verified = {}
    for key, role in wanted.items():
        field = found[key]
        typ = field.get("field_type")
        if not isinstance(typ, str) or typ not in FIELD_TYPES[role]:
            raise TargetValidationError("BUSINESS_FIELD_TYPE_UNSUPPORTED", field_key=key, role=role,
                                        observed_type=typ if isinstance(typ, str) else "unrecognized",
                                        supported_types=sorted(FIELD_TYPES[role]))
        definition = {"field_key": key, "field_type": typ}
        if typ == "select":
            # Both formats were independently observed. Never merge the two:
            # conflicting candidate vocabularies must remain a diagnostic.
            native = "option" in field
            if native and "options" in field:
                raise TargetValidationError("BUSINESS_FIELD_CANDIDATES_UNVERIFIED", field_key=key,
                                            check="ambiguous_candidate_contract")
            options = field.get("option" if native else "options")
            if not isinstance(options, list) or not options or len(options) > 2000:
                raise TargetValidationError("BUSINESS_FIELD_CANDIDATES_UNVERIFIED", field_key=key)
            candidates = {}
            id_key, label_key = ("option_id", "option_name") if native else ("value", "label")
            for option in options:
                value = _scalar(option.get(id_key)) if isinstance(option, dict) else None
                label = option.get(label_key) if isinstance(option, dict) else None
                if value is None or not isinstance(label, str) or not label.strip() or value in candidates:
                    raise TargetValidationError("BUSINESS_FIELD_CANDIDATES_UNVERIFIED", field_key=key)
                candidates[value] = label
            definition["candidates"] = candidates
            if native:
                definition["candidate_contract"] = "option_id/option_name"
        verified[key] = definition
    return verified


def field_value(fields, metadata, key):
    if key not in fields:
        raise TargetValidationError("BUSINESS_TARGET_FIELD_MISSING", field_key=key)
    raw = fields[key]
    if metadata[key]["field_type"] == "text":
        if not isinstance(raw, str) or not raw.strip():
            raise TargetValidationError("BUSINESS_FIELD_VALUE_UNVERIFIED", field_key=key)
        return raw, raw
    if metadata[key]["field_type"] == "select":
        if isinstance(raw, dict):
            if "value" in raw and "option_id" in raw:
                raise TargetValidationError("BUSINESS_FIELD_VALUE_UNVERIFIED", field_key=key,
                                            check="ambiguous_select_value")
            id_key = "option_id" if "option_id" in raw else "value"
            value = _scalar(raw.get(id_key))
        else:
            value = _scalar(raw)
        candidates = metadata[key]["candidates"]
        if value not in candidates:
            raise TargetValidationError("BUSINESS_FIELD_CANDIDATE_MISMATCH", field_key=key)
        label = candidates[value]
        if isinstance(raw, dict) and any(name in raw and raw[name] != label
                                         for name in ("label", "option_name")):
            raise TargetValidationError("BUSINESS_FIELD_CANDIDATE_MISMATCH", field_key=key)
        return value, label
    raise TargetValidationError("BUSINESS_FIELD_TYPE_UNSUPPORTED", field_key=key)


def native_metadata(metadata):
    """Native contracts require the separately verified business-code field."""
    return any(row.get("field_type") in ("multi-file", "workitem_related_select")
               or row.get("candidate_contract") == "option_id/option_name"
               for row in metadata.values())


def validate_project_metadata(binding, rows):
    key = binding.get("project_code_field")
    if not key:
        raise TargetValidationError("BUSINESS_TARGET_CONFIG_INCOMPLETE",
                                    missing_config=["project_code_field"])
    matches = [row for row in _definitions(rows) if row.get("field_key") == key]
    if len(matches) != 1:
        code = "BUSINESS_FIELD_METADATA_AMBIGUOUS" if matches else "BUSINESS_FIELD_METADATA_MISSING"
        raise TargetValidationError(code, field_key=key, role="project_code_field")
    if matches[0].get("field_type") != "text":
        raise TargetValidationError("BUSINESS_FIELD_TYPE_UNSUPPORTED", field_key=key,
                                    role="project_code_field", supported_types=["text"])
    return {key: {"field_key": key, "field_type": "text"}}


def project_identity(binding, project, metadata=None):
    attr = project.get("work_item_attribute", {})
    if (not isinstance(attr, dict) or _scalar(attr.get("work_item_id")) != binding["project"]
            or not isinstance(attr.get("owned_project"), dict)
            or attr["owned_project"].get("key") != binding["space"]
            or not isinstance(attr.get("work_item_type"), dict)
            or attr["work_item_type"].get("key") != binding["project_type"]):
        raise TargetValidationError("BUSINESS_PROJECT_IDENTITY_CHANGED", check="project_attributes")
    code_field = binding.get("project_code_field")
    if code_field:
        if (not isinstance(metadata, dict) or code_field not in metadata
                or metadata[code_field].get("field_type") != "text"):
            raise TargetValidationError("BUSINESS_PROJECT_CODE_UNVERIFIED", check="project_code_metadata")
        rows = project.get("work_item_fields")
        if not isinstance(rows, list):
            raise TargetValidationError("BUSINESS_PROJECT_CODE_UNVERIFIED", check="project_code_fields")
        matches = [row for row in rows if isinstance(row, dict) and row.get("key") == code_field]
        if len(matches) != 1:
            raise TargetValidationError("BUSINESS_PROJECT_CODE_UNVERIFIED", check="single_project_code_field")
        code = matches[0].get("value")
        if not isinstance(code, str) or business_ids(code) != [code]:
            raise TargetValidationError("BUSINESS_PROJECT_CODE_UNVERIFIED", check="exact_project_code_field")
        codes = [code]
    else:
        # Compatibility with the older explicit synthetic contract only. The
        # live/native reader requires project_code_field before calling here.
        title = attr.get("work_item_name")
        codes = business_ids(title) if isinstance(title, str) else []
        if len(codes) != 1:
            raise TargetValidationError("BUSINESS_PROJECT_CODE_UNVERIFIED", check="single_project_code")
    if codes[0] != binding["project_code"]:
        raise TargetValidationError("BUSINESS_PROJECT_CODE_MISMATCH", check="project_code")
    return attr


def target_identity(binding, fields, metadata):
    project_key = binding["project_field"]
    if project_key not in fields:
        raise TargetValidationError("BUSINESS_PROJECT_RELATION_MISSING", field_key=project_key)
    relation = fields[project_key]
    if not isinstance(relation, dict) or _scalar(relation.get("id")) is None:
        raise TargetValidationError("BUSINESS_PROJECT_RELATION_UNVERIFIED", field_key=project_key)
    if _scalar(relation["id"]) != binding["project"]:
        raise TargetValidationError("BUSINESS_TARGET_CHANGED", check="project_relation", field_key=project_key)
    node, _ = field_value(fields, metadata, binding["node_field"])
    if node != binding["node"]:
        raise TargetValidationError("BUSINESS_TARGET_CHANGED", check="node_relation", field_key=binding["node_field"])
    kind, label = field_value(fields, metadata, binding["document_kind_field"])
    if label in GENERIC_DOCUMENT_LABELS:
        raise TargetValidationError("BUSINESS_DOCUMENT_IDENTITY_UNVERIFIED",
                                    field_key=binding["document_kind_field"], check="generic_document_category")
    mapped = binding.get("document_type_bindings", {}).get(kind)
    named = DOCUMENT_NAMES.get(label)
    if mapped and named and mapped != named:
        raise TargetValidationError("BUSINESS_DOCUMENT_KIND_MISMATCH", check="candidate_label_binding")
    observed = mapped or named
    if observed is None:
        raise TargetValidationError("BUSINESS_DOCUMENT_IDENTITY_UNVERIFIED", field_key=binding["document_kind_field"])
    if observed != binding["document_type"]:
        raise TargetValidationError("BUSINESS_DOCUMENT_KIND_MISMATCH", field_key=binding["document_kind_field"])
    # These selections affect protected-write semantics too. Unknown values or
    # stale labels must not get past target resolution.
    for role in ("approval_field", "delivery_mode_field"):
        field_value(fields, metadata, binding[role])
    return {"project_code": binding["project_code"], "doc_type": observed}, kind


def immutable_binding(binding, metadata, identity, kind, project_metadata=None):
    keys = ("space", "project", "project_type", "node", "deliverable", "type", "url",
            "unreviewed_value", *FIELD_TYPES)
    payload = {"binding": {key: binding[key] for key in keys},
               "metadata": metadata, "identity": identity, "kind": kind,
               "document_type_bindings": binding.get("document_type_bindings", {})}
    if binding.get("project_code_field"):
        payload["binding"]["project_code_field"] = binding["project_code_field"]
        payload["project_metadata"] = project_metadata
    return fingerprint(payload)
