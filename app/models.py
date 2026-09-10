from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field


class Arm(str, Enum):
    A = "self_service"
    B = "rag"
    C = "agent"


class Category(str, Enum):
    TIMETABLE = "timetable"
    ENROLMENT = "enrolment"
    OUT_OF_SCOPE = "out_of_scope"
    RESTRICTED = "restricted_or_uncertain"


class Status(str, Enum):
    NEED_FIELDS = "need_fields"
    AWAITING_APPROVAL = "awaiting_approval"
    SENT = "sent"
    VERIFIED = "verified"
    ABSTAINED = "abstained"
    STOP_HUMAN = "stop_human"
    FAILED = "failed"
    FORM_READY = "form_ready"
    RAG_ONLY = "rag_only"
    UNKNOWN = "unknown"
    BLOCKED = "blocked"


class Origin(str, Enum):
    USER = "user"
    SOURCE = "source"
    SYSTEM = "system"


class FieldVal(BaseModel):
    value: str | None = None
    origin: Origin
    quote: str | None = None


class PolicyRef(BaseModel):
    source_id: str
    excerpt_id: str
    quote: str
    tags: list[str] = Field(default_factory=list)


class Package(BaseModel):
    category: Category
    summary: str
    fields: dict[str, FieldVal]
    missing: list[str]
    policy_refs: list[PolicyRef]
    routing: str
    escalation: bool
    approval_required: bool
    action_status: Status
    package_hash: str = ""
    destination: str | None = None
    trace: dict = Field(default_factory=dict)


CLAIM = "ENGINEERING DRY-RUN. Scripted staff-minute model. Not a measured evaluation. Not realised cash savings."
