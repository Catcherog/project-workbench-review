"""Canonical business identity, independent of wording, producer and channel.

Use the existing AM database/transaction in production. This standalone table is
an executable migration contract, not another source of task state. Identity
creation requires resolved business keys. Similar titles are never auto-merged.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import sqlite3


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class BusinessIdentity:
    tenant_id: str
    project_ref: str
    business_object_id: str
    action_code: str
    cycle_id: str

    def __post_init__(self) -> None:
        for value in self.__dict__.values():
            if not isinstance(value, str) or not value.strip() or len(value) > 256:
                raise ValueError("RESOLVED_BUSINESS_IDENTITY_REQUIRED")

    @property
    def canonical_id(self) -> str:
        return "task_" + digest(self.__dict__)


class IdentityRegistry:
    """Caller supplies a trusted owner identity and an explicit alias decision.

    The decision_id records an existing reviewed migration/association operation;
    it is not an authentication mechanism. The AM callback must authenticate the
    actor before entering here. Tenant/owner bindings are configured, not input
    copied from an inbound payload.
    """
    def __init__(self, path: str, tenant_id: str, owner_id: str):
        if not tenant_id or not owner_id:
            raise ValueError("IDENTITY_SCOPE_REQUIRED")
        self.tenant_id, self.owner_id = tenant_id, owner_id
        self.db = sqlite3.connect(path, timeout=5, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS fi_identities(
                tenant_id TEXT NOT NULL, canonical_id TEXT NOT NULL,
                business_json TEXT NOT NULL,
                PRIMARY KEY(tenant_id, canonical_id));
            CREATE TABLE IF NOT EXISTS fi_aliases(
                tenant_id TEXT NOT NULL, producer TEXT NOT NULL,
                external_id TEXT NOT NULL, canonical_id TEXT NOT NULL,
                decision_id TEXT NOT NULL, actor_id TEXT NOT NULL,
                PRIMARY KEY(tenant_id,producer,external_id),
                FOREIGN KEY(tenant_id,canonical_id)
                    REFERENCES fi_identities(tenant_id,canonical_id));
        """)

    def close(self) -> None:
        self.db.close()

    def register(self, identity: BusinessIdentity) -> str:
        if identity.tenant_id != self.tenant_id:
            raise ValueError("TENANT_MISMATCH")
        self.db.execute("INSERT OR IGNORE INTO fi_identities VALUES(?,?,?)",
                        (self.tenant_id, identity.canonical_id,
                         json.dumps(identity.__dict__, ensure_ascii=False, sort_keys=True)))
        return identity.canonical_id

    def bind_alias(self, producer: str, external_id: str, canonical_id: str,
                   *, actor_id: str, decision_id: str) -> str:
        if actor_id != self.owner_id:
            raise ValueError("OWNER_ONLY")
        if any(not isinstance(v, str) or not v.strip() or len(v) > 256
               for v in (producer, external_id, canonical_id, decision_id)):
            raise ValueError("REVIEWED_ALIAS_REQUIRED")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.db.execute("SELECT canonical_id FROM fi_identities WHERE tenant_id=? AND canonical_id=?",
                                  (self.tenant_id, canonical_id)).fetchone()
            if row is None:
                raise ValueError("UNKNOWN_CANONICAL_TASK")
            previous = self.db.execute("SELECT canonical_id FROM fi_aliases WHERE tenant_id=? AND producer=? AND external_id=?",
                                       (self.tenant_id, producer, external_id)).fetchone()
            if previous and previous["canonical_id"] != canonical_id:
                raise ValueError("ALIAS_ALREADY_BOUND_REVIEW_MERGE_REQUIRED")
            self.db.execute("INSERT OR IGNORE INTO fi_aliases VALUES(?,?,?,?,?,?)",
                            (self.tenant_id, producer, external_id, canonical_id, decision_id, actor_id))
            self.db.commit()
            return canonical_id
        except BaseException:
            self.db.rollback()
            raise

    def resolve(self, producer: str, external_id: str) -> str | None:
        row = self.db.execute("SELECT canonical_id FROM fi_aliases WHERE tenant_id=? AND producer=? AND external_id=?",
                              (self.tenant_id, producer, external_id)).fetchone()
        return row[0] if row else None

