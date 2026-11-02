"""Evidence-backed task projections; no model call, network, or message sending.

This portable reference store is for isolated tests. In AM, adapt these contracts
to the existing FactEngine and ActionItems repositories rather than creating a
second authoritative task database. Caller authentication, source entitlement,
semantic review, and fresh platform ACL checks belong to trusted AM adapters.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import sqlite3
from typing import Any, Iterator, Mapping, Sequence
from zoneinfo import ZoneInfo


class EvidenceError(ValueError):
    """Invalid evidence or an unsafe transition."""


class ConcurrentUpdate(EvidenceError):
    """The task or read checkpoint changed after it was inspected."""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _hash(value: Any) -> str:
    return sha256(_json(value).encode("utf-8")).hexdigest()


def _time(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise EvidenceError("time must be ISO 8601 with an explicit UTC offset") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise EvidenceError("naive time is not evidence")
    return result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def display_time(source_time: str, target_zone: str = "Asia/Shanghai") -> str:
    """Convert a source timestamp only; never rewrite times in message bodies."""
    return _time(source_time).astimezone(ZoneInfo(target_zone)).isoformat()


@dataclass(frozen=True)
class EvidenceRef:
    source_key: str
    version: str
    digest: str
    acl_version: str

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidenceRef":
        return cls(**{name: value[name] for name in ("source_key", "version", "digest", "acl_version")})


@dataclass(frozen=True)
class SourceEvidence:
    tenant_id: str
    namespace: str
    source_type: str
    scope_id: str
    native_id: str
    version: str
    text: str
    event_time: str
    observed_at: str
    acl_version: str
    audience_keys: tuple[str, ...] = ()
    stable_id: bool = True
    retracted: bool = False
    version_seq: int | None = None
    replaces_version: str | None = None
    source_timezone: str | None = None
    sensitivity: str = "internal"

    def __post_init__(self) -> None:
        for name in ("tenant_id", "namespace", "source_type", "scope_id", "native_id", "version", "acl_version"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise EvidenceError(f"{name} must be nonempty")
        _time(self.event_time)
        _time(self.observed_at)
        if self.version_seq is not None and (not isinstance(self.version_seq, int) or isinstance(self.version_seq, bool) or self.version_seq < 0):
            raise EvidenceError("version_seq must be an authoritative nonnegative integer")
        if self.sensitivity not in {"internal", "restricted", "private", "public"}:
            raise EvidenceError("unsupported sensitivity")
        if not isinstance(self.text, str):
            raise EvidenceError("source text must be a string")
        object.__setattr__(self, "audience_keys", tuple(sorted(set(self.audience_keys))))

    @property
    def source_key(self) -> str:
        # Same source identity across scanners: namespace is the source platform,
        # not the producer name. Producer-specific cursors remain separate.
        return _hash([self.tenant_id, self.namespace, self.source_type, self.scope_id, self.native_id])

    @property
    def body_digest(self) -> str:
        return sha256(self.text.encode("utf-8")).hexdigest()

    @property
    def digest(self) -> str:
        value = asdict(self)
        value.pop("observed_at")  # A reread is not an edit.
        return _hash(value)

    @property
    def ref(self) -> EvidenceRef:
        return EvidenceRef(self.source_key, self.version, self.digest, self.acl_version)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceEvidence":
        return cls(**dict(value))


@dataclass(frozen=True)
class IngestResult:
    ref: EvidenceRef
    status: str  # inserted, duplicate, advanced, historical, conflict, unordered


@dataclass(frozen=True)
class CoverageKey:
    producer: str
    source_type: str
    scope_id: str


@dataclass(frozen=True)
class ReadResult:
    key: CoverageKey
    status: str  # success, partial, failed, skipped
    started_at: str
    finished_at: str
    expected_version: int
    cursor: str | None = None
    cursor_seq: int | None = None
    reason: str | None = None
    scheduled_at: str | None = None


@dataclass(frozen=True)
class TaskSeed:
    task_id: str
    canonical_key: str
    action: str
    evidence_refs: tuple[EvidenceRef, ...] = ()
    project_id: str | None = None
    owner_id: str | None = None
    deadline_text: str | None = None
    business_timezone: str | None = None
    origin: str = "legacy_import"  # user_direct, legacy_import, trusted_adapter
    purpose: str = "execution"  # execution, approval_submission
    acceptance_required: bool = True
    deliverable_key: str | None = None  # This action's target artifact, not any contextual file.


FIELD_VALUES: dict[str, set[str] | None] = {
    "execution": {"unknown", "planned", "in_progress", "done", "blocked", "cancelled"},
    "response": {"not_required", "pending", "acknowledged"},
    "delivery": {"unknown", "pending", "delivered"},
    "plan_delivery": {"unknown", "pending", "delivered"},
    "release_materials": {"unknown", "pending", "ready"},
    "sample_arrival": {"unknown", "planned", "arrived"},
    "acceptance": {"not_required", "pending", "accepted", "rejected"},
    "approval": {"unknown", "pending", "approved", "withdrawn", "rejected"},
    "external_release": {"unknown", "forbidden", "approved", "sent"},
    "actual_start": None,
    "actual_release": None,
    "planned_start": None,
    "planned_release": None,
    "deadline_text": None,
    "owner_id": None,
    "project_id": None,
    "action": None,
    "risk": None,
    "blocker": None,
    "completion_condition": None,
    "test_overview": None,
}


@dataclass(frozen=True)
class QuoteSpan:
    ref: EvidenceRef
    start: int
    end: int
    quote: str


@dataclass(frozen=True)
class FactProposal:
    task_id: str
    field: str
    value: str
    quotes: tuple[QuoteSpan, ...]
    created_at: str
    supersedes: tuple[str, ...] = ()
    reasoning: str = ""
    response_to: str | None = None
    subject_key: str | None = None


@dataclass(frozen=True)
class EvidenceSnapshot:
    tenant_id: str
    task_versions: tuple[tuple[str, int], ...]
    refs: tuple[EvidenceRef, ...]
    coverage_versions: tuple[tuple[CoverageKey, int], ...] = ()
    created_at: str = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "EvidenceSnapshot":
        return cls(
            tenant_id=value["tenant_id"],
            task_versions=tuple((str(task), int(version)) for task, version in value["task_versions"]),
            refs=tuple(EvidenceRef.from_dict(ref) for ref in value["refs"]),
            coverage_versions=tuple((CoverageKey(**key), int(version)) for key, version in value.get("coverage_versions", ())),
            created_at=value["created_at"],
        )

    @property
    def digest(self) -> str:
        return _hash(self.to_dict())


SCHEMA = """
CREATE TABLE IF NOT EXISTS ef_heads (
 tenant TEXT NOT NULL, source_key TEXT NOT NULL, version TEXT NOT NULL,
 conflicted INTEGER NOT NULL DEFAULT 0, state_version INTEGER NOT NULL DEFAULT 1,
 PRIMARY KEY(tenant,source_key));
CREATE TABLE IF NOT EXISTS ef_evidence (
 tenant TEXT NOT NULL, source_key TEXT NOT NULL, version TEXT NOT NULL,
 digest TEXT NOT NULL, record_json TEXT NOT NULL,
 PRIMARY KEY(tenant,source_key,version));
CREATE TABLE IF NOT EXISTS ef_conflicts (
 tenant TEXT NOT NULL, conflict_id TEXT NOT NULL, source_key TEXT NOT NULL,
 record_json TEXT NOT NULL, PRIMARY KEY(tenant,conflict_id));
CREATE TABLE IF NOT EXISTS ef_tasks (
 tenant TEXT NOT NULL, task_id TEXT NOT NULL, canonical_key TEXT NOT NULL,
 seed_json TEXT NOT NULL, version INTEGER NOT NULL,
 PRIMARY KEY(tenant,task_id), UNIQUE(tenant,canonical_key));
CREATE TABLE IF NOT EXISTS ef_seed_refs (
 tenant TEXT NOT NULL,task_id TEXT NOT NULL,source_key TEXT NOT NULL,
 version TEXT NOT NULL, PRIMARY KEY(tenant,task_id,source_key,version));
CREATE TABLE IF NOT EXISTS ef_seed_history (
 tenant TEXT NOT NULL,task_id TEXT NOT NULL,task_version INTEGER NOT NULL,
 seed_json TEXT NOT NULL,reviewer TEXT NOT NULL,explanation TEXT NOT NULL,
 reviewed_at TEXT NOT NULL,PRIMARY KEY(tenant,task_id,task_version));
CREATE TABLE IF NOT EXISTS ef_source_resolutions (
 tenant TEXT NOT NULL,source_key TEXT NOT NULL,state_version INTEGER NOT NULL,
 resolution_json TEXT NOT NULL,PRIMARY KEY(tenant,source_key,state_version));
CREATE TABLE IF NOT EXISTS ef_claims (
 tenant TEXT NOT NULL,claim_id TEXT NOT NULL,task_id TEXT NOT NULL,
 field TEXT NOT NULL,value TEXT NOT NULL,status TEXT NOT NULL,
 proposal_json TEXT NOT NULL,reviewer TEXT,reviewed_at TEXT,
 PRIMARY KEY(tenant,claim_id));
CREATE TABLE IF NOT EXISTS ef_claim_refs (
 tenant TEXT NOT NULL,claim_id TEXT NOT NULL,source_key TEXT NOT NULL,
 version TEXT NOT NULL, PRIMARY KEY(tenant,claim_id,source_key,version));
CREATE INDEX IF NOT EXISTS ef_claims_task ON ef_claims(tenant,task_id,field,status);
CREATE TABLE IF NOT EXISTS ef_coverage (
 tenant TEXT NOT NULL,producer TEXT NOT NULL,source_type TEXT NOT NULL,
 scope_id TEXT NOT NULL,version INTEGER NOT NULL,cursor TEXT,cursor_seq INTEGER,
 result_json TEXT NOT NULL,
 PRIMARY KEY(tenant,producer,source_type,scope_id));
CREATE TABLE IF NOT EXISTS ef_read_history (
 tenant TEXT NOT NULL,run_id TEXT NOT NULL,result_json TEXT NOT NULL,
 PRIMARY KEY(tenant,run_id));
CREATE TABLE IF NOT EXISTS ef_gaps (
 tenant TEXT NOT NULL,gap_id TEXT NOT NULL,producer TEXT NOT NULL,
 source_type TEXT NOT NULL,scope_id TEXT NOT NULL,description TEXT NOT NULL,
 opened_at TEXT NOT NULL,resolution_json TEXT,
 PRIMARY KEY(tenant,gap_id));
"""


class EvidenceLedger:
    """Tenant-scoped reference ledger; database operations use short transactions.

    This is an in-process trusted domain API, not an HTTP authorization boundary.
    Each call opens its own SQLite connection, allowing competing workers to
    serialize through BEGIN IMMEDIATE. Use a file path, not ':memory:'.
    """

    def __init__(self, path: str, tenant_id: str):
        if path == ":memory:" or not tenant_id:
            raise EvidenceError("use a file-backed database and nonempty tenant")
        self.path, self.tenant_id = path, tenant_id
        with self._db(write=True) as db:
            db.executescript(SCHEMA)
            # Only the portable reference store schema; not a production AM migration.
            if "state_version" not in {row["name"] for row in db.execute("PRAGMA table_info(ef_heads)")}:
                db.execute("ALTER TABLE ef_heads ADD COLUMN state_version INTEGER NOT NULL DEFAULT 1")

    @contextmanager
    def _db(self, write: bool = False) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        try:
            db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield db
            if db.in_transaction:
                db.commit()
        except BaseException:
            if db.in_transaction:
                db.rollback()
            raise
        finally:
            db.close()

    def ingest(self, evidence: SourceEvidence) -> IngestResult:
        with self._db(write=True) as db:
            return self._ingest(db, evidence)

    def ingest_batch(self, evidence: Sequence[SourceEvidence], read: ReadResult) -> tuple[IngestResult, ...]:
        """Persist a successful batch and its scoped cursor atomically.

        Read failure may carry partial observations, but it never advances the
        cursor. A caller must not advance a checkpoint before processing a batch.
        """
        with self._db(write=True) as db:
            results = tuple(self._ingest(db, item) for item in evidence)
            self._record_read(db, read)
            return results

    def _ingest(self, db: sqlite3.Connection, item: SourceEvidence) -> IngestResult:
        if item.tenant_id != self.tenant_id:
            raise EvidenceError("cross-tenant evidence")
        old = db.execute("SELECT * FROM ef_evidence WHERE tenant=? AND source_key=? AND version=?", (self.tenant_id, item.source_key, item.version)).fetchone()
        head = db.execute("SELECT * FROM ef_heads WHERE tenant=? AND source_key=?", (self.tenant_id, item.source_key)).fetchone()
        if old:
            if old["digest"] == item.digest:
                return IngestResult(item.ref, "duplicate")
            self._source_conflict(db, item)
            return IngestResult(item.ref, "conflict")
        db.execute("INSERT INTO ef_evidence VALUES (?,?,?,?,?)", (self.tenant_id, item.source_key, item.version, item.digest, _json(asdict(item))))
        if head is None:
            db.execute("INSERT INTO ef_heads (tenant,source_key,version,conflicted,state_version) VALUES (?,?,?,0,1)", (self.tenant_id, item.source_key, item.version))
            return IngestResult(item.ref, "inserted")
        previous = self._get_evidence(db, EvidenceRef(item.source_key, head["version"], "", ""), strict=False)
        relation = "unordered"
        if previous.version_seq is not None and item.version_seq is not None:
            if item.version_seq > previous.version_seq:
                relation = "advanced"
            elif item.version_seq < previous.version_seq:
                relation = "historical"
            else:
                relation = "conflict"
        elif item.replaces_version == previous.version:
            relation = "advanced"
        if relation == "advanced" and not head["conflicted"]:
            db.execute("UPDATE ef_heads SET version=?,state_version=state_version+1 WHERE tenant=? AND source_key=?", (item.version, self.tenant_id, item.source_key))
            self._invalidate_source(db, item.source_key)
        elif relation in {"unordered", "conflict"} or head["conflicted"]:
            # A conflict never disappears merely because a later event arrives.
            self._source_conflict(db, item)
            if head["conflicted"]:
                relation = "conflict"
        return IngestResult(item.ref, relation)

    def _source_conflict(self, db: sqlite3.Connection, item: SourceEvidence) -> None:
        inserted = db.execute("INSERT OR IGNORE INTO ef_conflicts VALUES (?,?,?,?)", (self.tenant_id, _hash([item.source_key, item.version, item.digest]), item.source_key, _json(asdict(item)))).rowcount
        head = db.execute("SELECT conflicted FROM ef_heads WHERE tenant=? AND source_key=?", (self.tenant_id, item.source_key)).fetchone()
        if inserted or not head["conflicted"]:
            db.execute("UPDATE ef_heads SET conflicted=1,state_version=state_version+1 WHERE tenant=? AND source_key=?", (self.tenant_id, item.source_key))
            self._invalidate_source(db, item.source_key)

    def source_state(self, source_key: str) -> dict[str, Any]:
        """Inspect a source's generation before explicit reconciliation."""
        with self._db() as db:
            row = db.execute("SELECT * FROM ef_heads WHERE tenant=? AND source_key=?", (self.tenant_id, source_key)).fetchone()
            if row is None:
                raise EvidenceError("unknown source")
            record = self._get_evidence(db, EvidenceRef(source_key, row["version"], "", ""), strict=False)
            return {"source_key": source_key, "head_ref": asdict(record.ref),
                    "conflicted": bool(row["conflicted"]), "state_version": row["state_version"]}

    def resolve_source_conflict(self, source_key: str, accepted_ref: EvidenceRef, reviewer_id: str,
                                expected_state_version: int, *, explanation: str,
                                reviewed_at: str | None = None) -> dict[str, Any]:
        """Trusted review picks an explicit stored source version, with CAS.

        No latest-wins or automatic recovery. Same-version contradictory variants
        stay archived; the accepted ref must identify an immutable canonical row.
        Reingesting a later genuine source version first permits choosing it.
        """
        if not reviewer_id.strip() or not explanation.strip():
            raise EvidenceError("source reconciliation needs reviewer and explanation")
        reviewed_at = reviewed_at or _now()
        _time(reviewed_at)
        with self._db(write=True) as db:
            head = db.execute("SELECT * FROM ef_heads WHERE tenant=? AND source_key=?", (self.tenant_id, source_key)).fetchone()
            if head is None or accepted_ref.source_key != source_key:
                raise EvidenceError("resolution must select this source's stored version")
            if head["state_version"] != expected_state_version:
                raise ConcurrentUpdate("source changed during reconciliation")
            if not head["conflicted"]:
                raise EvidenceError("source has no conflict to resolve")
            selected = self._get_evidence(db, accepted_ref)
            if not selected.stable_id:
                raise EvidenceError("provisional evidence cannot resolve an authoritative source conflict")
            resolution = {"previous_head_version": head["version"], "accepted_ref": asdict(accepted_ref),
                          "reviewer_id": reviewer_id, "explanation": explanation, "reviewed_at": reviewed_at}
            db.execute("INSERT INTO ef_source_resolutions VALUES (?,?,?,?)", (self.tenant_id, source_key, expected_state_version + 1, _json(resolution)))
            db.execute("UPDATE ef_heads SET version=?,conflicted=0,state_version=state_version+1 WHERE tenant=? AND source_key=?", (selected.version, self.tenant_id, source_key))
            self._invalidate_source(db, source_key)
            return {"source_key": source_key, "head_ref": asdict(accepted_ref), "conflicted": False,
                    "state_version": expected_state_version + 1}

    def _invalidate_source(self, db: sqlite3.Connection, source_key: str) -> None:
        rows = db.execute("""SELECT DISTINCT c.task_id FROM ef_claims c JOIN ef_claim_refs r
            ON c.tenant=r.tenant AND c.claim_id=r.claim_id WHERE c.tenant=? AND r.source_key=?
            UNION SELECT task_id FROM ef_seed_refs WHERE tenant=? AND source_key=?""", (self.tenant_id, source_key, self.tenant_id, source_key)).fetchall()
        for row in rows:
            db.execute("UPDATE ef_tasks SET version=version+1 WHERE tenant=? AND task_id=?", (self.tenant_id, row["task_id"]))

    def _get_evidence(self, db: sqlite3.Connection, ref: EvidenceRef, *, strict: bool = True) -> SourceEvidence:
        row = db.execute("SELECT * FROM ef_evidence WHERE tenant=? AND source_key=? AND version=?", (self.tenant_id, ref.source_key, ref.version)).fetchone()
        if row is None:
            raise EvidenceError("unknown evidence in this tenant")
        result = SourceEvidence.from_dict(json.loads(row["record_json"]))
        if strict and result.ref != ref:
            raise EvidenceError("evidence digest or ACL version mismatch")
        return result

    def get_evidence(self, ref: EvidenceRef) -> SourceEvidence:
        with self._db() as db:
            return self._get_evidence(db, ref)

    def _ref_problem(self, db: sqlite3.Connection, ref: EvidenceRef) -> str | None:
        try:
            record = self._get_evidence(db, ref)
        except EvidenceError:
            return "evidence_not_found_or_mismatch"
        head = db.execute("SELECT * FROM ef_heads WHERE tenant=? AND source_key=?", (self.tenant_id, ref.source_key)).fetchone()
        if head["conflicted"]:
            return "source_conflict"
        if head["version"] != ref.version:
            return "source_changed"
        if record.retracted:
            return "source_retracted"
        return None

    def create_task(self, seed: TaskSeed) -> dict[str, Any]:
        if not all((seed.task_id, seed.canonical_key, seed.action.strip())):
            raise EvidenceError("task ID, canonical key, and action are required")
        if seed.origin not in {"legacy_import", "user_direct", "trusted_adapter"}:
            raise EvidenceError("unsupported task origin")
        if seed.purpose not in {"execution", "approval_submission"}:
            raise EvidenceError("unsupported task purpose")
        if seed.business_timezone:
            ZoneInfo(seed.business_timezone)
        with self._db(write=True) as db:
            for ref in seed.evidence_refs:
                source = self._get_evidence(db, ref)
                if source.sensitivity == "private":
                    raise EvidenceError("private material cannot seed a project task")
            old = db.execute("SELECT * FROM ef_tasks WHERE tenant=? AND (task_id=? OR canonical_key=?)", (self.tenant_id, seed.task_id, seed.canonical_key)).fetchone()
            if old:
                if old["seed_json"] != _json(asdict(seed)):
                    raise EvidenceError("canonical task already exists; reconcile mapping explicitly")
                return self._task_view(db, seed.task_id)
            db.execute("INSERT INTO ef_tasks VALUES (?,?,?,?,1)", (self.tenant_id, seed.task_id, seed.canonical_key, _json(asdict(seed))))
            db.execute("INSERT INTO ef_seed_history VALUES (?,?,1,?,'initial_import','initial seed',?)", (self.tenant_id, seed.task_id, _json(asdict(seed)), _now()))
            for ref in seed.evidence_refs:
                db.execute("INSERT OR IGNORE INTO ef_seed_refs VALUES (?,?,?,?)", (self.tenant_id, seed.task_id, ref.source_key, ref.version))
            return self._task_view(db, seed.task_id)

    def review_rebase_task(self, task_id: str, new_seed_refs: Sequence[EvidenceRef], reviewer_id: str,
                          expected_task_version: int, *, explanation: str,
                          reviewed_at: str | None = None) -> dict[str, Any]:
        """Revalidate unchanged task identity/fields against newer source versions.

        The trusted reviewer must verify that the normalized seed fields remain
        supported. This cannot change owner/project/action, swap unrelated source
        identities, or drop evidence. Changed meanings use reviewed field claims.
        """
        if not reviewer_id.strip() or not explanation.strip():
            raise EvidenceError("task rebase needs reviewer and explanation")
        reviewed_at = reviewed_at or _now()
        _time(reviewed_at)
        with self._db(write=True) as db:
            row = self._task_row(db, task_id)
            if row["version"] != expected_task_version:
                raise ConcurrentUpdate("task changed during evidence rebase")
            seed = json.loads(row["seed_json"])
            old_refs = tuple(EvidenceRef.from_dict(value) for value in seed["evidence_refs"])
            new_refs = tuple(sorted(set(new_seed_refs), key=lambda ref: (ref.source_key, ref.version, ref.digest)))
            if not new_refs or {ref.source_key for ref in new_refs} != {ref.source_key for ref in old_refs}:
                raise EvidenceError("rebase must retain the exact source identities; no drop or swap")
            if len({ref.source_key for ref in new_refs}) != len(new_refs):
                raise EvidenceError("rebase requires one current version per source")
            for ref in new_refs:
                source = self._get_evidence(db, ref)
                if self._ref_problem(db, ref) or source.sensitivity == "private":
                    raise EvidenceError("rebase requires current, accessible, unconflicted evidence")
            if set(new_refs) == set(old_refs):
                raise EvidenceError("rebase must select an actual source version change")
            seed["evidence_refs"] = [asdict(ref) for ref in new_refs]
            payload = _json(seed)
            next_version = expected_task_version + 1
            db.execute("UPDATE ef_tasks SET seed_json=?,version=? WHERE tenant=? AND task_id=?", (payload, next_version, self.tenant_id, task_id))
            db.execute("INSERT INTO ef_seed_history VALUES (?,?,?,?,?,?,?)", (self.tenant_id, task_id, next_version, payload, reviewer_id, explanation, reviewed_at))
            db.execute("DELETE FROM ef_seed_refs WHERE tenant=? AND task_id=?", (self.tenant_id, task_id))
            for ref in new_refs:
                db.execute("INSERT INTO ef_seed_refs VALUES (?,?,?,?)", (self.tenant_id, task_id, ref.source_key, ref.version))
            return self._task_view(db, task_id)

    def seed_history(self, task_id: str) -> tuple[dict[str, Any], ...]:
        with self._db() as db:
            self._task_row(db, task_id)
            rows = db.execute("SELECT * FROM ef_seed_history WHERE tenant=? AND task_id=? ORDER BY task_version", (self.tenant_id, task_id)).fetchall()
            return tuple({"task_version": row["task_version"], "seed": json.loads(row["seed_json"]),
                          "reviewer_id": row["reviewer"], "explanation": row["explanation"],
                          "reviewed_at": row["reviewed_at"]} for row in rows)

    def _task_row(self, db: sqlite3.Connection, task_id: str) -> sqlite3.Row:
        row = db.execute("SELECT * FROM ef_tasks WHERE tenant=? AND task_id=?", (self.tenant_id, task_id)).fetchone()
        if row is None:
            raise EvidenceError("unknown task in this tenant")
        return row

    def propose(self, proposal: FactProposal) -> str:
        if proposal.field not in FIELD_VALUES or not proposal.value or not proposal.quotes:
            raise EvidenceError("known field, value, and exact source quotes are required")
        allowed = FIELD_VALUES[proposal.field]
        if allowed is not None and proposal.value not in allowed:
            raise EvidenceError("unsupported normalized value")
        _time(proposal.created_at)
        if proposal.field == "response" and proposal.value == "acknowledged" and not proposal.response_to:
            raise EvidenceError("acknowledgement must identify the pending response claim")
        identity = asdict(proposal)
        identity.pop("created_at")
        identity.pop("reasoning")
        claim_id = "claim_" + _hash([self.tenant_id, identity])
        with self._db(write=True) as db:
            task = self._task_row(db, proposal.task_id)
            if proposal.field == "delivery":
                target = json.loads(task["seed_json"]).get("deliverable_key")
                if not target or proposal.subject_key != target:
                    raise EvidenceError("delivery must name this task's exact target artifact; contextual plans use plan_delivery")
            for span in proposal.quotes:
                source = self._get_evidence(db, span.ref)
                if (not isinstance(span.start, int) or not isinstance(span.end, int) or span.start < 0
                        or span.end <= span.start or span.end > len(source.text)
                        or source.text[span.start:span.end] != span.quote or not span.quote.strip()):
                    raise EvidenceError("quote does not match source character span")
                if self._ref_problem(db, span.ref):
                    raise EvidenceError("proposal source is no longer current")
                if source.sensitivity == "private":
                    raise EvidenceError("private conversation is not project task material")
            previous = db.execute("SELECT claim_id FROM ef_claims WHERE tenant=? AND claim_id=?", (self.tenant_id, claim_id)).fetchone()
            if previous:
                return claim_id
            db.execute("INSERT INTO ef_claims VALUES (?,?,?,?,?,'candidate',?,NULL,NULL)", (self.tenant_id, claim_id, proposal.task_id, proposal.field, proposal.value, _json(asdict(proposal))))
            for span in proposal.quotes:
                db.execute("INSERT OR IGNORE INTO ef_claim_refs VALUES (?,?,?,?)", (self.tenant_id, claim_id, span.ref.source_key, span.ref.version))
            db.execute("UPDATE ef_tasks SET version=version+1 WHERE tenant=? AND task_id=?", (self.tenant_id, proposal.task_id))
        return claim_id

    @staticmethod
    def _proposal_refs(row: sqlite3.Row) -> tuple[EvidenceRef, ...]:
        data = json.loads(row["proposal_json"])
        return tuple(EvidenceRef.from_dict(span["ref"]) for span in data["quotes"])

    def accept_claim(self, claim_id: str, reviewer_id: str, expected_task_version: int, *, reviewed_at: str | None = None) -> dict[str, Any]:
        """Accept only after a trusted semantic reviewer checked entailment.

        Exact quotes prove provenance, NOT that the normalized meaning is true.
        reviewer_id is an audit label, never authentication. Public callers/LLMs
        must not be allowed to invoke this operation or choose reviewer_id.
        """
        if not reviewer_id.strip():
            raise EvidenceError("a trusted reviewer identity is required")
        reviewed_at = reviewed_at or _now()
        _time(reviewed_at)
        with self._db(write=True) as db:
            row = db.execute("SELECT * FROM ef_claims WHERE tenant=? AND claim_id=?", (self.tenant_id, claim_id)).fetchone()
            if row is None:
                raise EvidenceError("unknown claim")
            task = self._task_row(db, row["task_id"])
            if task["version"] != expected_task_version:
                raise ConcurrentUpdate("task changed before semantic acceptance")
            if row["status"] != "candidate":
                raise EvidenceError("only a candidate can be accepted")
            for ref in self._proposal_refs(row):
                if self._ref_problem(db, ref):
                    raise EvidenceError("source changed before semantic acceptance")
            data = json.loads(row["proposal_json"])
            predecessors = tuple(data["supersedes"])
            for predecessor in predecessors:
                old = db.execute("SELECT * FROM ef_claims WHERE tenant=? AND claim_id=?", (self.tenant_id, predecessor)).fetchone()
                if old is None or old["task_id"] != row["task_id"] or old["field"] != row["field"] or old["status"] != "accepted":
                    raise EvidenceError("supersedes must name accepted claims of the same task and field")
            if row["field"] == "response" and row["value"] == "acknowledged":
                target = db.execute("SELECT * FROM ef_claims WHERE tenant=? AND claim_id=?", (self.tenant_id, data["response_to"])).fetchone()
                if target is None or target["task_id"] != row["task_id"] or target["field"] != "response" or target["value"] != "pending" or target["status"] != "accepted" or target["claim_id"] not in predecessors:
                    raise EvidenceError("acknowledgement must supersede its exact pending response")
            for predecessor in predecessors:
                db.execute("UPDATE ef_claims SET status='superseded' WHERE tenant=? AND claim_id=?", (self.tenant_id, predecessor))
            db.execute("UPDATE ef_claims SET status='accepted',reviewer=?,reviewed_at=? WHERE tenant=? AND claim_id=?", (reviewer_id, reviewed_at, self.tenant_id, claim_id))
            db.execute("UPDATE ef_tasks SET version=version+1 WHERE tenant=? AND task_id=?", (self.tenant_id, row["task_id"]))
            return self._task_view(db, row["task_id"])

    def reject_claim(self, claim_id: str, reviewer_id: str, expected_task_version: int) -> dict[str, Any]:
        if not reviewer_id.strip():
            raise EvidenceError("reviewer required")
        with self._db(write=True) as db:
            row = db.execute("SELECT * FROM ef_claims WHERE tenant=? AND claim_id=?", (self.tenant_id, claim_id)).fetchone()
            if row is None or row["status"] != "candidate":
                raise EvidenceError("unknown candidate")
            task = self._task_row(db, row["task_id"])
            if task["version"] != expected_task_version:
                raise ConcurrentUpdate("task changed")
            db.execute("UPDATE ef_claims SET status='rejected',reviewer=?,reviewed_at=? WHERE tenant=? AND claim_id=?", (reviewer_id, _now(), self.tenant_id, claim_id))
            db.execute("UPDATE ef_tasks SET version=version+1 WHERE tenant=? AND task_id=?", (self.tenant_id, row["task_id"]))
            return self._task_view(db, row["task_id"])

    def _task_view(self, db: sqlite3.Connection, task_id: str) -> dict[str, Any]:
        task = self._task_row(db, task_id)
        seed = json.loads(task["seed_json"])
        claims = db.execute("SELECT * FROM ef_claims WHERE tenant=? AND task_id=? ORDER BY claim_id", (self.tenant_id, task_id)).fetchall()
        fields: dict[str, dict[str, Any]] = {}
        candidates: list[dict[str, Any]] = []
        stale: list[dict[str, Any]] = []
        for claim in claims:
            if claim["status"] in {"rejected", "superseded"}:
                continue
            refs = self._proposal_refs(claim)
            issues = tuple(problem for ref in refs if (problem := self._ref_problem(db, ref)))
            item = {"claim_id": claim["claim_id"], "field": claim["field"], "value": claim["value"], "evidence": [asdict(ref) for ref in refs]}
            if issues:
                stale.append({**item, "reasons": list(issues)})
            elif claim["status"] == "candidate":
                candidates.append(item)
            else:
                entry = fields.setdefault(claim["field"], {"values": [], "claims": [], "conflict": False})
                if claim["value"] not in entry["values"]:
                    entry["values"].append(claim["value"])
                entry["claims"].append(item)
                entry["conflict"] = len(entry["values"]) > 1

        seed_refs = tuple(EvidenceRef.from_dict(ref) for ref in seed["evidence_refs"])
        seed_issues = [problem for ref in seed_refs if (problem := self._ref_problem(db, ref))]

        def current(name: str, default: Any = None) -> Any:
            entry = fields.get(name)
            if entry and not entry["conflict"]:
                return entry["values"][0]
            if entry:
                return None
            return default

        seed_default = lambda name: None if seed_issues else seed.get(name)
        execution = current("execution", "unknown")
        response = current("response", "not_required")
        delivery = current("delivery", "unknown")
        acceptance = current("acceptance", "pending" if seed["acceptance_required"] else "not_required")
        has_conflict = any(entry["conflict"] for entry in fields.values())
        completion = execution == "done" and (not seed["acceptance_required"] or acceptance == "accepted")
        completion_claims = [claim["claim_id"] for name in ("execution", "acceptance") for claim in fields.get(name, {}).get("claims", [])]
        obsolete = seed["purpose"] == "approval_submission" and current("approval") == "approved"
        if has_conflict or stale or seed_issues:
            business_state, legacy_status = "needs_verification", "waiting"
            completion = False
        elif execution == "cancelled":
            business_state, legacy_status = "cancelled", "cancelled"
        elif completion:
            business_state, legacy_status = "completed", "closed"
        elif obsolete:
            business_state, legacy_status = "superseded_action", "closed"
        elif execution == "blocked":
            business_state, legacy_status = "blocked", "blocked"
        elif delivery == "delivered":
            business_state, legacy_status = "delivered_waiting_acceptance", "submitted"
        elif execution == "in_progress":
            business_state, legacy_status = "in_progress", "in_progress"
        else:
            business_state, legacy_status = "open", "waiting"
        project = current("project_id", seed_default("project_id"))
        owner = current("owner_id", seed_default("owner_id"))
        missing = [name for name, value in (("project_id", project), ("owner_id", owner)) if not value]
        all_refs = list(seed_refs)
        for claim in claims:
            if claim["status"] == "accepted":
                all_refs.extend(self._proposal_refs(claim))
        provisional = not all_refs or any(not self._get_evidence(db, ref).stable_id for ref in all_refs)
        return {
            "task_id": task_id, "canonical_key": seed["canonical_key"], "version": task["version"],
            "action": current("action", seed_default("action")), "project_id": project, "owner_id": owner,
            "deadline_text": current("deadline_text", seed_default("deadline_text")),
            "business_timezone": seed["business_timezone"], "origin": seed["origin"],
            "deliverable_key": seed.get("deliverable_key"),
            "execution": execution, "response": response, "delivery": delivery, "acceptance": acceptance,
            "business_state": business_state, "legacy_action_status": legacy_status,
            "business_completed": completion, "obsolete_action": obsolete,
            "completion_claim_ids": completion_claims if completion else [],
            "fields": fields, "candidates": candidates, "stale": stale,
            "seed_evidence": [asdict(ref) for ref in seed_refs], "seed_issues": seed_issues,
            "conflict": has_conflict, "provisional": provisional, "missing": missing,
            "followup_ready": not (has_conflict or stale or seed_issues or candidates or missing or provisional or completion or obsolete or execution == "cancelled"),
        }

    def task_view(self, task_id: str) -> dict[str, Any]:
        with self._db() as db:
            return self._task_view(db, task_id)

    def project_view(self, project_id: str) -> dict[str, Any]:
        with self._db() as db:
            rows = db.execute("SELECT task_id FROM ef_tasks WHERE tenant=? ORDER BY task_id", (self.tenant_id,)).fetchall()
            all_tasks = [self._task_view(db, row["task_id"]) for row in rows]
            tasks = [task for task in all_tasks if task["project_id"] == project_id]
            unresolved = [task["task_id"] for task in all_tasks if not task["project_id"]]
            return {"project_id": project_id, "tasks": tasks, "unmapped_task_ids": unresolved,
                    "coverage": self._coverage_view(db), "progress_percentage": None,
                    "coverage_statement": "Only observed, authorized scopes; missing data is not an empty task list."}

    def record_read(self, result: ReadResult) -> None:
        with self._db(write=True) as db:
            self._record_read(db, result)

    def _record_read(self, db: sqlite3.Connection, result: ReadResult) -> None:
        if result.status not in {"success", "partial", "failed", "skipped"}:
            raise EvidenceError("unsupported read result")
        if _time(result.finished_at) < _time(result.started_at):
            raise EvidenceError("read finished before it started")
        if result.scheduled_at:
            _time(result.scheduled_at)
        if result.status != "success" and (result.cursor is not None or result.cursor_seq is not None):
            raise EvidenceError("only complete success for this exact scope can advance a cursor")
        if result.status == "success" and result.cursor is None:
            raise EvidenceError("successful read must identify its processed position")
        key = (self.tenant_id, result.key.producer, result.key.source_type, result.key.scope_id)
        old = db.execute("SELECT * FROM ef_coverage WHERE tenant=? AND producer=? AND source_type=? AND scope_id=?", key).fetchone()
        version = old["version"] if old else 0
        if result.expected_version != version:
            raise ConcurrentUpdate("read checkpoint changed; overlapping scanner must reconcile")
        if old and _time(json.loads(old["result_json"])["finished_at"]) > _time(result.finished_at):
            raise ConcurrentUpdate("older read result cannot replace a later outcome")
        if old and result.cursor_seq is not None and old["cursor_seq"] is not None and result.cursor_seq < old["cursor_seq"]:
            raise EvidenceError("cursor regression")
        cursor = result.cursor if result.status == "success" else (old["cursor"] if old else None)
        cursor_seq = result.cursor_seq if result.status == "success" else (old["cursor_seq"] if old else None)
        payload = _json(asdict(result))
        db.execute("INSERT OR REPLACE INTO ef_coverage VALUES (?,?,?,?,?,?,?,?)", (*key, version + 1, cursor, cursor_seq, payload))
        db.execute("INSERT OR IGNORE INTO ef_read_history VALUES (?,?,?)", (self.tenant_id, _hash(asdict(result)), payload))

    def checkpoint(self, key: CoverageKey) -> dict[str, Any]:
        with self._db() as db:
            row = db.execute("SELECT * FROM ef_coverage WHERE tenant=? AND producer=? AND source_type=? AND scope_id=?", (self.tenant_id, key.producer, key.source_type, key.scope_id)).fetchone()
            return {"version": row["version"], "cursor": row["cursor"], "cursor_seq": row["cursor_seq"], "result": json.loads(row["result_json"])} if row else {"version": 0, "cursor": None, "cursor_seq": None, "result": None}

    def add_gap(self, gap_id: str, key: CoverageKey, description: str, opened_at: str) -> None:
        _time(opened_at)
        if not gap_id or not description.strip():
            raise EvidenceError("gap needs an ID and explanation")
        with self._db(write=True) as db:
            old = db.execute("SELECT * FROM ef_gaps WHERE tenant=? AND gap_id=?", (self.tenant_id, gap_id)).fetchone()
            expected = (key.producer, key.source_type, key.scope_id, description, opened_at)
            if old:
                actual = tuple(old[name] for name in ("producer", "source_type", "scope_id", "description", "opened_at"))
                if actual != expected:
                    raise EvidenceError("gap ID cannot be reused for a different missing range")
                return
            db.execute("INSERT INTO ef_gaps VALUES (?,?,?,?,?,?,?,NULL)", (self.tenant_id, gap_id, *expected))

    def resolve_gap(self, gap_id: str, *, resolution_ref: EvidenceRef, reviewer_id: str, resolved_at: str) -> None:
        """Explicit trusted verification of an exact gap; never called by a tick."""
        _time(resolved_at)
        if not reviewer_id.strip():
            raise EvidenceError("gap closure requires a reviewer")
        with self._db(write=True) as db:
            row = db.execute("SELECT * FROM ef_gaps WHERE tenant=? AND gap_id=?", (self.tenant_id, gap_id)).fetchone()
            if row is None:
                raise EvidenceError("unknown gap")
            if self._ref_problem(db, resolution_ref):
                raise EvidenceError("gap completion proof is stale")
            proof = self._get_evidence(db, resolution_ref)
            if not proof.stable_id or proof.source_type != "coverage_proof":
                raise EvidenceError("require a stable coverage_proof from the trusted reconciliation adapter")
            if proof.scope_id != row["scope_id"]:
                raise EvidenceError("coverage proof is for a different scope")
            payload = {"ref": asdict(resolution_ref), "reviewer_id": reviewer_id, "resolved_at": resolved_at}
            db.execute("UPDATE ef_gaps SET resolution_json=? WHERE tenant=? AND gap_id=?", (_json(payload), self.tenant_id, gap_id))

    def _coverage_view(self, db: sqlite3.Connection) -> dict[str, Any]:
        reads = db.execute("SELECT * FROM ef_coverage WHERE tenant=? ORDER BY producer,source_type,scope_id", (self.tenant_id,)).fetchall()
        gaps = db.execute("SELECT * FROM ef_gaps WHERE tenant=? AND resolution_json IS NULL ORDER BY gap_id", (self.tenant_id,)).fetchall()
        return {"scopes": [{"key": {name: row[name] for name in ("producer", "source_type", "scope_id")}, "version": row["version"], "cursor": row["cursor"], "last_result": json.loads(row["result_json"])} for row in reads], "open_gaps": [dict(row) for row in gaps]}

    def coverage_view(self) -> dict[str, Any]:
        with self._db() as db:
            return self._coverage_view(db)

    def snapshot(self, task_ids: Sequence[str], *, required_coverage: Sequence[CoverageKey] = (), created_at: str | None = None) -> EvidenceSnapshot:
        if not task_ids:
            raise EvidenceError("an empty snapshot cannot authorize followup")
        created_at = created_at or _now()
        _time(created_at)
        with self._db() as db:
            versions: list[tuple[str, int]] = []
            refs: dict[tuple[str, str], EvidenceRef] = {}
            for task_id in sorted(set(task_ids)):
                row = self._task_row(db, task_id)
                versions.append((task_id, row["version"]))
                seed = json.loads(row["seed_json"])
                for value in seed["evidence_refs"]:
                    ref = EvidenceRef.from_dict(value)
                    refs[(ref.source_key, ref.version)] = ref
                claims = db.execute("SELECT * FROM ef_claims WHERE tenant=? AND task_id=? AND status='accepted'", (self.tenant_id, task_id)).fetchall()
                for claim in claims:
                    for ref in self._proposal_refs(claim):
                        refs[(ref.source_key, ref.version)] = ref
            coverage: list[tuple[CoverageKey, int]] = []
            for key in sorted(set(required_coverage), key=lambda item: (item.producer, item.source_type, item.scope_id)):
                row = db.execute("SELECT version FROM ef_coverage WHERE tenant=? AND producer=? AND source_type=? AND scope_id=?", (self.tenant_id, key.producer, key.source_type, key.scope_id)).fetchone()
                coverage.append((key, row["version"] if row else 0))
            return EvidenceSnapshot(self.tenant_id, tuple(versions), tuple(refs[key] for key in sorted(refs)), tuple(coverage), created_at)

    def check_snapshot(self, snapshot: EvidenceSnapshot, audience_keys: Sequence[str], *, now: str | None = None, max_age_seconds: int | None = None) -> tuple[str, ...]:
        """Return blocking reasons, not an authorization grant.

        Audience keys are exact person/chat audience identities from a trusted
        resolver. A chat key means its whole audience, not merely mentioned users.
        This local check cannot prove current platform ACLs or source freshness.
        """
        reasons: set[str] = set()
        if snapshot.tenant_id != self.tenant_id:
            return ("cross_tenant_snapshot",)
        if not snapshot.task_versions or not snapshot.refs:
            return ("empty_snapshot",)
        if not audience_keys:
            reasons.add("missing_audience")
        if max_age_seconds is not None:
            age = (_time(now or _now()) - _time(snapshot.created_at)).total_seconds()
            if age < 0 or age > max_age_seconds:
                reasons.add("snapshot_expired_or_future")
        with self._db() as db:
            for task_id, version in snapshot.task_versions:
                try:
                    task = self._task_view(db, task_id)
                except EvidenceError:
                    reasons.add("unknown_task")
                    continue
                if task["version"] != version:
                    reasons.add("task_changed")
                if not task["followup_ready"]:
                    reasons.add("task_not_followup_ready")
            # Reconstruct dependencies: a caller must not omit inconvenient refs.
            expected_refs: set[EvidenceRef] = set()
            for task_id, _ in snapshot.task_versions:
                try:
                    row = self._task_row(db, task_id)
                except EvidenceError:
                    continue
                expected_refs.update(EvidenceRef.from_dict(ref) for ref in json.loads(row["seed_json"])["evidence_refs"])
                for claim in db.execute("SELECT * FROM ef_claims WHERE tenant=? AND task_id=? AND status='accepted'", (self.tenant_id, task_id)).fetchall():
                    expected_refs.update(self._proposal_refs(claim))
            if set(snapshot.refs) != expected_refs:
                reasons.add("snapshot_dependencies_mismatch")
            for ref in snapshot.refs:
                if problem := self._ref_problem(db, ref):
                    reasons.add(problem)
                    continue
                evidence = self._get_evidence(db, ref)
                if not evidence.stable_id:
                    reasons.add("provisional_source")
                if evidence.sensitivity == "private":
                    reasons.add("private_source")
                if any(audience not in evidence.audience_keys for audience in audience_keys):
                    reasons.add("audience_not_allowed")
            for key, version in snapshot.coverage_versions:
                row = db.execute("SELECT * FROM ef_coverage WHERE tenant=? AND producer=? AND source_type=? AND scope_id=?", (self.tenant_id, key.producer, key.source_type, key.scope_id)).fetchone()
                if row is None or row["version"] != version:
                    reasons.add("coverage_changed_or_unknown")
                    continue
                if json.loads(row["result_json"])["status"] != "success":
                    reasons.add("coverage_unhealthy")
                gap = db.execute("SELECT gap_id FROM ef_gaps WHERE tenant=? AND producer=? AND source_type=? AND scope_id=? AND resolution_json IS NULL", (self.tenant_id, key.producer, key.source_type, key.scope_id)).fetchone()
                if gap:
                    reasons.add("coverage_gap")
        return tuple(sorted(reasons))
