"""Durable bridge between the executable evidence and admission contracts.

Production must implement the live attestor with AM's existing source/permission
adapters. No default successful attestation exists. Local stored evidence proves
what was read, not that the platform has not changed since then.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3
from typing import Callable, Protocol, Sequence

from .evidence import CoverageKey, EvidenceLedger, EvidenceSnapshot as SourceSnapshot
from .followup import Draft, EvidenceSnapshot as SendSnapshot, GateResult


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value: object) -> str:
    return hashlib.sha256(_json(value).encode()).hexdigest()


def audience_key(draft: Draft) -> str:
    return ("chat:" if draft.target.kind == "group" else "user:") + draft.target.target_id


@dataclass(frozen=True)
class LiveAttestation:
    tenant_id: str
    owner_id: str
    snapshot_digest: str
    audience_key: str
    body_sha256: str
    checked_at: datetime
    valid_until: datetime
    allowed: bool
    policy_revision: str
    reason: str = ""


class LiveAttestor(Protocol):
    def __call__(self, tenant_id: str, owner_id: str, snapshot: SourceSnapshot,
                 audience: str, body_sha256: str) -> LiveAttestation:
        """Refresh exact current sources, disclosure policy and dirty markers.

        Verify the whole body, including project/action titles and inferred
        question context. Do not equate read access with permission to disclose.
        The returned grant is created by a trusted adapter, never from the LLM.
        """
        ...


class EvidenceBridge:
    """Local durable snapshot + mandatory fresh authority check.

    required_coverage is server configuration. A model cannot drop a failing
    source, omit a coverage gap or choose a different tenant by editing a draft.
    """
    def __init__(self, db_path: str, ledger: EvidenceLedger, *,
                 required_coverage: Callable[[str], Sequence[CoverageKey]],
                 live_attestor: LiveAttestor,
                 clock: Callable[[], datetime] | None = None,
                 max_snapshot_age: timedelta = timedelta(minutes=15),
                 max_attestation_age: timedelta = timedelta(seconds=60)):
        self.db_path, self.ledger = db_path, ledger
        self.required_coverage, self.live_attestor = required_coverage, live_attestor
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.max_snapshot_age, self.max_attestation_age = max_snapshot_age, max_attestation_age
        if min(max_snapshot_age.total_seconds(), max_attestation_age.total_seconds()) <= 0:
            raise ValueError("FRESHNESS_BOUNDS_REQUIRED")
        with sqlite3.connect(db_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS fi_snapshot_bindings(
                tenant_id TEXT NOT NULL,binding_id TEXT NOT NULL,task_id TEXT NOT NULL,
                snapshot_json TEXT NOT NULL,audience TEXT NOT NULL,body_sha256 TEXT NOT NULL,
                disclosure_policy_revision TEXT NOT NULL,
                PRIMARY KEY(tenant_id,binding_id))""")

    def capture(self, task_id: str, audience: str, body: str, *, disclosure_policy_revision: str) -> SendSnapshot:
        if not isinstance(disclosure_policy_revision, str) or not disclosure_policy_revision.strip():
            raise ValueError("REVIEWED_DISCLOSURE_POLICY_REVISION_REQUIRED")
        now = self.clock()
        if now.tzinfo is None:
            raise ValueError("AWARE_CLOCK_REQUIRED")
        snapshot = self.ledger.snapshot((task_id,), required_coverage=self.required_coverage(task_id),
                                        created_at=now.isoformat())
        body_hash = hashlib.sha256(body.encode()).hexdigest()
        binding_id = _hash([snapshot.digest, audience, body_hash, disclosure_policy_revision])
        with sqlite3.connect(self.db_path) as db:
            db.execute("INSERT OR IGNORE INTO fi_snapshot_bindings VALUES(?,?,?,?,?,?,?)",
                       (snapshot.tenant_id, binding_id, task_id, _json(snapshot.to_dict()), audience, body_hash,
                        disclosure_policy_revision))
        return self._send_snapshot(binding_id, snapshot, audience, disclosure_policy_revision)

    @staticmethod
    def _send_snapshot(binding_id: str, snapshot: SourceSnapshot, audience: str, policy_revision: str) -> SendSnapshot:
        versions = {"binding": binding_id}
        # The admission contract requires matching dependency key sets. The
        # binding entry covers the immutable snapshot and full-body audience.
        acl = {"binding": _hash([snapshot.digest, policy_revision])}
        for ref in snapshot.refs:
            key = ref.source_key + "/" + ref.version
            versions[key] = ref.digest
            acl[key] = ref.acl_version
        return SendSnapshot(versions, acl, _hash(snapshot.task_versions), (audience,))

    def __call__(self, tenant_id: str, owner_id: str, draft: Draft) -> GateResult:
        try:
            if tenant_id != self.ledger.tenant_id:
                return GateResult(False, "evidence_tenant_mismatch")
            binding_id = draft.evidence.versions.get("binding")
            with sqlite3.connect(self.db_path) as db:
                db.row_factory = sqlite3.Row
                row = db.execute("SELECT * FROM fi_snapshot_bindings WHERE tenant_id=? AND binding_id=?",
                                 (tenant_id, binding_id)).fetchone()
            if row is None or row["task_id"] != draft.task_id:
                return GateResult(False, "unknown_evidence_binding")
            snapshot = SourceSnapshot.from_dict(json.loads(row["snapshot_json"]))
            audience = audience_key(draft)
            body_hash = hashlib.sha256(draft.body.encode()).hexdigest()
            if row["audience"] != audience or row["body_sha256"] != body_hash:
                return GateResult(False, "disclosure_body_or_audience_changed")
            if asdict(draft.evidence) != asdict(self._send_snapshot(binding_id, snapshot, audience,
                                                                  row["disclosure_policy_revision"])):
                return GateResult(False, "evidence_dependencies_omitted_or_changed")
            expected_coverage = set(self.required_coverage(draft.task_id))
            if {key for key, _ in snapshot.coverage_versions} != expected_coverage:
                return GateResult(False, "required_coverage_changed")
            now = self.clock()
            problems = self.ledger.check_snapshot(snapshot, (audience,), now=now.isoformat(),
                                                   max_age_seconds=int(self.max_snapshot_age.total_seconds()))
            if problems:
                return GateResult(False, ",".join(problems))
            # Even a newly captured local snapshot cannot attest platform freshness.
            live = self.live_attestor(tenant_id, owner_id, snapshot, audience, body_hash)
            if (live.tenant_id, live.owner_id, live.snapshot_digest, live.audience_key, live.body_sha256) != (
                    tenant_id, owner_id, snapshot.digest, audience, body_hash):
                return GateResult(False, "live_attestation_binding_mismatch")
            if live.policy_revision != row["disclosure_policy_revision"]:
                return GateResult(False, "disclosure_policy_revision_changed")
            if (live.checked_at.tzinfo is None or live.valid_until.tzinfo is None or
                    live.checked_at > now or now - live.checked_at > self.max_attestation_age or
                    live.valid_until <= now or not live.policy_revision):
                return GateResult(False, "live_attestation_stale")
            if live.allowed is not True:
                return GateResult(False, live.reason or "live_permission_not_explicitly_true")
            return GateResult(True)
        except Exception:
            # Do not leak private source contents in an error or accept on outage.
            return GateResult(False, "evidence_or_live_policy_unavailable")

