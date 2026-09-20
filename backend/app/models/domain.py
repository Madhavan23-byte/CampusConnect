"""
CampusConnect — SQLAlchemy Domain Models
All database tables are defined here using SQLAlchemy 2.0 mapped_column syntax.

CRITICAL DESIGN NOTES:
- UUID primary keys everywhere (no sequential integers exposed externally)
- TIMESTAMPTZ for all timestamps (stored in UTC)
- Soft delete via deleted_at (never hard-delete institutional records)
- Optimistic locking on EventRequest via version_lock
- Hall booking protected by PostgreSQL EXCLUDE USING gist constraint (in migration)
- JSONB used only for true schema-less data (snapshots, facility lists)
- Decimal/Numeric for all financial amounts (never Float)
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import (
    ActualExpenseStatus,
    ActualIncomeStatus,
    AuditAction,
    BudgetLineItemCategory,
    CashAdvanceStatus,
    ClubMemberRole,
    DocumentType,
    EventRequestStatus,
    EventStatus,
    EventType,
    FinanceVerificationStatus,
    IncomeSourceType,
    NotificationType,
    PaymentMethod,
    PostEventReportStatus,
    ResourceRequestStatus,
    ResourceType,
    SettlementPaymentType,
    SettlementStatus,
    SettlementType,
    UserRole,
    VenueRequestStatus,
    WorkflowInstanceStatus,
    WorkflowStepStatus,
)
from app.models.mixins import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin

# Dialect-portable JSON type: native JSONB on PostgreSQL, standard JSON on SQLite
JSONType = JSONB().with_variant(JSON(), "sqlite")

# ============================================================================
# USER
# ============================================================================


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """
    System user. Every person interacting with CampusConnect has exactly one account.
    Role is a single system-level role (not a many-to-many permission table in Phase 1).
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        String(50),  # Store as string for Alembic compatibility; validated at app level
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Login security
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Department / designation (optional metadata)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    designation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Relationships
    clubs_as_advisor: Mapped[list["Club"]] = relationship(
        "Club", back_populates="faculty_advisor", foreign_keys="Club.faculty_advisor_id"
    )
    club_memberships: Mapped[list["ClubMember"]] = relationship("ClubMember", back_populates="user")
    event_requests_submitted: Mapped[list["EventRequest"]] = relationship(
        "EventRequest", back_populates="submitted_by_user", foreign_keys="EventRequest.submitted_by"
    )
    notifications: Mapped[list["Notification"]] = relationship(
        "Notification", back_populates="recipient"
    )

    __table_args__ = (
        CheckConstraint("length(email) > 0", name="ck_users_email_not_empty"),
        CheckConstraint("length(full_name) > 0", name="ck_users_full_name_not_empty"),
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email} role={self.role}>"


# ============================================================================
# REFRESH TOKEN
# ============================================================================


class RefreshToken(Base, UUIDPrimaryKeyMixin):
    """
    Stored refresh tokens for JWT refresh token rotation.
    On every refresh, old token is invalidated and a new one is issued.
    """

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    user: Mapped["User"] = relationship("User")

    @property
    def is_valid(self) -> bool:
        return self.revoked_at is None and self.expires_at > datetime.now(UTC)


# ============================================================================
# PASSWORD RESET TOKEN
# ============================================================================


class PasswordResetToken(Base, UUIDPrimaryKeyMixin):
    """One-time password reset tokens. Expire after configured TTL."""

    __tablename__ = "password_reset_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship("User")


# ============================================================================
# EMAIL VERIFICATION TOKEN
# ============================================================================


class EmailVerificationToken(Base, UUIDPrimaryKeyMixin):
    """Tokens for verifying college email addresses at registration."""

    __tablename__ = "email_verification_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship("User")


# ============================================================================
# CLUB
# ============================================================================


class Club(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """
    A college club. Every EventRequest originates from a Club.
    A Club has one assigned Faculty Advisor.
    """

    __tablename__ = "clubs"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)  # URL-friendly
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    faculty_advisor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    academic_year: Mapped[str] = mapped_column(String(10), nullable=False)  # e.g. "2026-27"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    # Relationships
    faculty_advisor: Mapped["User | None"] = relationship(
        "User", back_populates="clubs_as_advisor", foreign_keys=[faculty_advisor_id]
    )
    members: Mapped[list["ClubMember"]] = relationship("ClubMember", back_populates="club")
    event_requests: Mapped[list["EventRequest"]] = relationship(
        "EventRequest", back_populates="club"
    )

    def __repr__(self) -> str:
        return f"<Club id={self.id} name={self.name}>"


class ClubMember(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Membership record linking a User to a Club with an internal role.
    member_role is a metadata label (SECRETARY/TREASURER/MEMBER) —
    it does NOT grant system permissions beyond what the user's UserRole provides.
    """

    __tablename__ = "club_members"

    club_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clubs.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    member_role: Mapped[ClubMemberRole] = mapped_column(
        String(20), default=ClubMemberRole.MEMBER, nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    club: Mapped["Club"] = relationship("Club", back_populates="members")
    user: Mapped["User"] = relationship("User", back_populates="club_memberships")

    __table_args__ = (
        UniqueConstraint("club_id", "user_id", name="uq_club_members_club_user"),
        Index("ix_club_members_club_id", "club_id"),
        Index("ix_club_members_user_id", "user_id"),
    )


# ============================================================================
# HALL
# ============================================================================


class Hall(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Venue/Hall available for booking.
    Facilities stored as JSONB list for flexibility.
    DEVELOPMENT SEED DATA: actual hall names must be configured via Admin UI.
    """

    __tablename__ = "halls"

    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    # JSONB list: ["projector", "sound_system", "stage", "ac", "lcd"]
    available_facilities: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    venue_requests: Mapped[list["VenueRequest"]] = relationship(
        "VenueRequest", back_populates="hall"
    )
    confirmed_bookings: Mapped[list["HallBookingConfirmed"]] = relationship(
        "HallBookingConfirmed", back_populates="hall"
    )

    __table_args__ = (CheckConstraint("capacity > 0", name="ck_halls_capacity_positive"),)

    def __repr__(self) -> str:
        return f"<Hall id={self.id} name={self.name} capacity={self.capacity}>"


class HallBookingConfirmed(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    A confirmed hall booking that exists when a VenueRequest is approved.
    The EXCLUDE USING gist constraint on this table prevents overlapping approved bookings.
    This is the source of truth for hall occupancy.

    IMPORTANT: The exclusion constraint is defined in the Alembic migration,
    not here in Python, because SQLAlchemy doesn't natively support EXCLUDE constraints.
    """

    __tablename__ = "hall_bookings_confirmed"

    hall_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("halls.id"), nullable=False, index=True
    )
    event_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("event_requests.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # One confirmed booking per event request
    )
    venue_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("venue_requests.id"),
        nullable=False,
    )
    booking_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # These are stored redundantly alongside the tstzrange for querying clarity
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    hall: Mapped["Hall"] = relationship("Hall", back_populates="confirmed_bookings")

    __table_args__ = (
        CheckConstraint("end_time > start_time", name="ck_hall_bookings_end_after_start"),
        # The EXCLUDE USING gist constraint is added in Alembic migration:
        # EXCLUDE USING gist (
        #   hall_id WITH =,
        #   tstzrange(start_time, end_time, '[)') WITH &&
        # ) WHERE (is_active = true)
        Index("ix_hall_bookings_hall_date", "hall_id", "booking_date"),
    )


# ============================================================================
# EVENT REQUEST (PROPOSAL LIFECYCLE)
# ============================================================================


class EventRequest(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """
    Central domain object. Represents an event proposal in its lifecycle.
    Separate from Event (confirmed approved reality).

    IMPORTANT:
    - version_lock enables optimistic concurrency control.
    - current_version tracks the latest submitted version number.
    - Status transitions are enforced by the approval service.
    """

    __tablename__ = "event_requests"

    club_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clubs.id"), nullable=False, index=True
    )
    submitted_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_type: Mapped[EventType] = mapped_column(String(30), nullable=False)
    expected_attendees: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Chief guest (optional)
    chief_guest_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chief_guest_designation: Mapped[str | None] = mapped_column(String(255), nullable=True)
    chief_guest_institution: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Proposal status and versioning
    status: Mapped[EventRequestStatus] = mapped_column(
        String(30), default=EventRequestStatus.DRAFT, nullable=False, index=True
    )
    current_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Optimistic locking — increment on every UPDATE
    version_lock: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    academic_year: Mapped[str] = mapped_column(String(10), nullable=False)
    # Idempotency key for submission endpoint
    idempotency_key: Mapped[str | None] = mapped_column(
        String(100), nullable=True, unique=True, index=True
    )
    # FK to the active workflow instance (set on submission)
    workflow_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "workflow_instances.id", use_alter=True, name="fk_event_requests_workflow_instance_id"
        ),
        nullable=True,
    )

    # Relationships
    club: Mapped["Club"] = relationship("Club", back_populates="event_requests")
    submitted_by_user: Mapped["User"] = relationship(
        "User", back_populates="event_requests_submitted", foreign_keys=[submitted_by]
    )
    versions: Mapped[list["EventRequestVersion"]] = relationship(
        "EventRequestVersion",
        back_populates="event_request",
        order_by="EventRequestVersion.version_number",
    )
    venue_request: Mapped["VenueRequest | None"] = relationship(
        "VenueRequest", back_populates="event_request", uselist=False
    )
    budget_proposal: Mapped["BudgetProposal | None"] = relationship(
        "BudgetProposal", back_populates="event_request", uselist=False
    )
    resource_requests: Mapped[list["ResourceRequest"]] = relationship(
        "ResourceRequest", back_populates="event_request"
    )
    documents: Mapped[list["Document"]] = relationship("Document", back_populates="event_request")
    workflow_instances: Mapped[list["WorkflowInstance"]] = relationship(
        "WorkflowInstance",
        back_populates="event_request",
        foreign_keys="WorkflowInstance.event_request_id",
        cascade="all, delete-orphan",
    )
    workflow_instance: Mapped["WorkflowInstance | None"] = relationship(
        "WorkflowInstance",
        foreign_keys=[workflow_instance_id],
        post_update=True,
    )
    event: Mapped["Event | None"] = relationship(
        "Event", back_populates="event_request", uselist=False
    )
    notifications: Mapped[list["Notification"]] = relationship(
        "Notification", back_populates="event_request"
    )

    __table_args__ = (
        Index("ix_event_requests_status_club", "status", "club_id"),
        Index("ix_event_requests_academic_year_status", "academic_year", "status"),
        CheckConstraint(
            "expected_attendees IS NULL OR expected_attendees > 0",
            name="ck_event_requests_attendees_positive",
        ),
    )

    def __repr__(self) -> str:
        return f"<EventRequest id={self.id} title={self.title!r} status={self.status}>"


class EventRequestVersion(Base, UUIDPrimaryKeyMixin):
    """
    Immutable snapshot of an EventRequest at submission time.
    Version 1 = initial submission. Version N = Nth resubmission after revision.
    Approvers review a specific version. Audit trail references version_number.

    IMMUTABILITY: Once created, this record must never be modified.
    The application service layer must enforce this.
    """

    __tablename__ = "event_request_versions"

    event_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("event_requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    # Full serialized snapshot of proposal at submission time
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    submitted_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Human-readable summary of changes from previous version
    change_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    event_request: Mapped["EventRequest"] = relationship("EventRequest", back_populates="versions")
    submitter: Mapped["User"] = relationship("User", foreign_keys=[submitted_by])

    __table_args__ = (
        UniqueConstraint(
            "event_request_id", "version_number", name="uq_event_request_versions_request_version"
        ),
        Index("ix_event_request_versions_request_id", "event_request_id"),
    )


# ============================================================================
# VENUE REQUEST
# ============================================================================


class VenueRequest(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Hall/venue requirement for an EventRequest.
    One EventRequest can have at most one VenueRequest in Phase 1.
    Status is managed by the Hall Incharge step in the approval chain.
    """

    __tablename__ = "venue_requests"

    event_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("event_requests.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # One venue request per event request
    )
    hall_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("halls.id"), nullable=False, index=True
    )
    requested_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_audience: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Facility requirements
    requires_stage: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_audio: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_lcd: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_ac: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_projector: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    additional_requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[VenueRequestStatus] = mapped_column(
        String(20), default=VenueRequestStatus.PENDING, nullable=False
    )
    # Set when Hall Incharge acts on the request
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    event_request: Mapped["EventRequest"] = relationship(
        "EventRequest", back_populates="venue_request"
    )
    hall: Mapped["Hall"] = relationship("Hall", back_populates="venue_requests")
    reviewer: Mapped["User | None"] = relationship("User", foreign_keys=[reviewed_by])

    __table_args__ = (
        CheckConstraint("end_time > start_time", name="ck_venue_requests_end_after_start"),
        Index("ix_venue_requests_hall_date", "hall_id", "requested_date"),
    )


# ============================================================================
# BUDGET PROPOSAL
# ============================================================================


class BudgetProposal(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Financial proposal for an event. One per EventRequest.
    Uses Numeric (not Float) for all monetary values.
    Finance Officer can verify/query this independently of main approval chain.
    """

    __tablename__ = "budget_proposals"

    event_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("event_requests.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    expected_income: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), default=Decimal("0.00"), nullable=False
    )
    institute_contribution: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), default=Decimal("0.00"), nullable=False
    )
    total_expected_expenditure: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), default=Decimal("0.00"), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Finance Officer verification (does not block approval chain in Phase 1)
    finance_status: Mapped[FinanceVerificationStatus] = mapped_column(
        String(20), default=FinanceVerificationStatus.PENDING, nullable=False
    )
    finance_verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    finance_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finance_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    event_request: Mapped["EventRequest"] = relationship(
        "EventRequest", back_populates="budget_proposal"
    )
    line_items: Mapped[list["BudgetLineItem"]] = relationship(
        "BudgetLineItem", back_populates="budget_proposal", cascade="all, delete-orphan"
    )
    finance_officer: Mapped["User | None"] = relationship(
        "User", foreign_keys=[finance_verified_by]
    )

    __table_args__ = (
        CheckConstraint("expected_income >= 0", name="ck_budget_proposals_income_non_negative"),
        CheckConstraint(
            "institute_contribution >= 0",
            name="ck_budget_proposals_contribution_non_negative",
        ),
        CheckConstraint(
            "total_expected_expenditure >= 0",
            name="ck_budget_proposals_expenditure_non_negative",
        ),
    )


class BudgetLineItem(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Individual budget line item. Category allows finance reporting by type."""

    __tablename__ = "budget_line_items"

    budget_proposal_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("budget_proposals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    category: Mapped[BudgetLineItemCategory] = mapped_column(String(30), nullable=False)
    estimated_amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Relationship
    budget_proposal: Mapped["BudgetProposal"] = relationship(
        "BudgetProposal", back_populates="line_items"
    )

    __table_args__ = (
        CheckConstraint("estimated_amount >= 0", name="ck_budget_line_items_amount_non_negative"),
    )


# ============================================================================
# RESOURCE REQUEST
# ============================================================================


class ResourceRequest(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Equipment/resource requirement for an event."""

    __tablename__ = "resource_requests"

    event_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("event_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resource_type: Mapped[ResourceType] = mapped_column(String(30), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ResourceRequestStatus] = mapped_column(
        String(20), default=ResourceRequestStatus.PENDING, nullable=False
    )
    managed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    # Relationship
    event_request: Mapped["EventRequest"] = relationship(
        "EventRequest", back_populates="resource_requests"
    )

    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_resource_requests_quantity_positive"),
    )


# ============================================================================
# DOCUMENT
# ============================================================================


class Document(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Uploaded document associated with an EventRequest.
    Files are stored with UUID-based names, never original filenames.
    Access requires authentication — never served from public static directory.
    """

    __tablename__ = "documents"

    event_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("event_requests.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    document_type: Mapped[DocumentType] = mapped_column(String(30), nullable=False)
    # Display name only — never used for file access
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    # UUID-based name used for actual storage — prevents path traversal/guessing
    stored_filename: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # Relative path within storage root (never absolute, never user-controlled)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Optional association with confirmed event for post-event evidence
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Optional unverified client-declared or EXIF geo coordinates
    geo_latitude: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=9, scale=6), nullable=True
    )
    geo_longitude: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=9, scale=6), nullable=True
    )
    geo_source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Optional SHA-256 digest for duplicate detection (Phase 2.2)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # Relationships
    event_request: Mapped["EventRequest"] = relationship("EventRequest", back_populates="documents")
    uploader: Mapped["User"] = relationship("User", foreign_keys=[uploaded_by])
    actual_expenses: Mapped[list["ActualExpense"]] = relationship(
        "ActualExpense", back_populates="bill_document"
    )
    actual_incomes: Mapped[list["ActualIncome"]] = relationship(
        "ActualIncome", back_populates="evidence_document"
    )
    settlement_payments: Mapped[list["SettlementPayment"]] = relationship(
        "SettlementPayment", back_populates="proof_document"
    )

    __table_args__ = (
        CheckConstraint("file_size_bytes > 0", name="ck_documents_file_size_positive"),
    )


# ============================================================================
# WORKFLOW ENGINE
# ============================================================================


class WorkflowTemplate(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """
    Configurable approval chain template.
    Admin configures which roles approve in which order.
    NOT hard-coded in Python — must be DB-driven.
    Different templates can be assigned to different event types.
    """

    __tablename__ = "workflow_templates"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # If event_type is NULL, this template applies to all event types
    event_type: Mapped[EventType | None] = mapped_column(String(30), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    # Relationships
    steps: Mapped[list["WorkflowTemplateStep"]] = relationship(
        "WorkflowTemplateStep",
        back_populates="template",
        order_by="WorkflowTemplateStep.step_order",
        cascade="all, delete-orphan",
    )
    instances: Mapped[list["WorkflowInstance"]] = relationship(
        "WorkflowInstance", back_populates="template"
    )

    __table_args__ = (
        # Only one default template at a time — enforced at application level
        # (partial unique index would work: CREATE UNIQUE INDEX WHERE is_default = true)
    )


class WorkflowTemplateStep(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    One step in a workflow template.
    required_role: which role must approve at this step.
    assigned_user_id: if set, this specific user is the approver.
                      if NULL, approver is resolved dynamically from club/system.
    """

    __tablename__ = "workflow_template_steps"

    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    step_name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Role required at this step
    required_role: Mapped[UserRole] = mapped_column(String(50), nullable=False)
    # If null: approver is resolved dynamically (e.g., the club's faculty advisor)
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    is_optional: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    template: Mapped["WorkflowTemplate"] = relationship("WorkflowTemplate", back_populates="steps")
    assigned_user: Mapped["User | None"] = relationship("User", foreign_keys=[assigned_user_id])

    __table_args__ = (
        UniqueConstraint(
            "template_id", "step_order", name="uq_workflow_template_steps_template_order"
        ),
        CheckConstraint("step_order > 0", name="ck_workflow_template_steps_order_positive"),
    )


class WorkflowInstance(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    A running instance of a workflow template for a specific EventRequest.
    Created on submission. A new instance is created on every resubmission.
    Previous instance is marked SUPERSEDED.
    """

    __tablename__ = "workflow_instances"

    template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_templates.id"), nullable=False
    )
    # FK back to EventRequest — note: EventRequest also has FK to WorkflowInstance
    # This bidirectional reference is intentional for query efficiency
    event_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("event_requests.id"), nullable=False
    )
    current_step_order: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[WorkflowInstanceStatus] = mapped_column(
        String(20), default=WorkflowInstanceStatus.IN_PROGRESS, nullable=False
    )
    version_number: Mapped[int] = mapped_column(
        Integer, nullable=False
    )  # Matches EventRequestVersion

    # Relationships
    template: Mapped["WorkflowTemplate"] = relationship(
        "WorkflowTemplate", back_populates="instances"
    )
    event_request: Mapped["EventRequest"] = relationship(
        "EventRequest",
        back_populates="workflow_instances",
        foreign_keys=[event_request_id],
    )
    steps: Mapped[list["WorkflowInstanceStep"]] = relationship(
        "WorkflowInstanceStep",
        back_populates="instance",
        order_by="WorkflowInstanceStep.step_order",
    )

    __table_args__ = (
        Index("ix_workflow_instances_event_request_id", "event_request_id"),
        Index("ix_workflow_instances_status", "status"),
    )


class WorkflowInstanceStep(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    A single step within a running workflow instance.
    Tracks which specific user reviewed which version of the proposal and what they decided.
    Immutable once acted upon — history must be preserved.
    """

    __tablename__ = "workflow_instance_steps"

    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_instances.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    template_step_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_template_steps.id"), nullable=False
    )
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    step_name: Mapped[str] = mapped_column(String(255), nullable=False)
    assigned_to: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    status: Mapped[WorkflowStepStatus] = mapped_column(
        String(30), default=WorkflowStepStatus.PENDING, nullable=False
    )
    action_taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    comments: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Which version of the proposal was reviewed at this step
    version_reviewed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Optimistic lock on step — prevents two simultaneous approvals of the same step
    step_version_lock: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Relationships
    instance: Mapped["WorkflowInstance"] = relationship("WorkflowInstance", back_populates="steps")
    assignee: Mapped["User"] = relationship("User", foreign_keys=[assigned_to])
    template_step: Mapped["WorkflowTemplateStep"] = relationship(
        "WorkflowTemplateStep", foreign_keys=[template_step_id]
    )

    __table_args__ = (
        UniqueConstraint(
            "instance_id", "step_order", name="uq_workflow_instance_steps_instance_order"
        ),
        Index("ix_workflow_instance_steps_assigned_status", "assigned_to", "status"),
    )


# ============================================================================
# EVENT (CONFIRMED APPROVED REALITY)
# ============================================================================


class Event(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """
    A confirmed event. Created automatically when an EventRequest is APPROVED.
    Core approved data is derived from the approved EventRequestVersion.
    Modification of an approved event requires a new EventRequest workflow.
    """

    __tablename__ = "events"

    event_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("event_requests.id"),
        nullable=False,
        unique=True,  # One event per approved request
    )
    # The specific approved version that created this event
    approved_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("event_request_versions.id"), nullable=False
    )
    club_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clubs.id"), nullable=False, index=True
    )
    hall_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("halls.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_type: Mapped[EventType] = mapped_column(String(30), nullable=False)
    event_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_attendees: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[EventStatus] = mapped_column(
        String(20), default=EventStatus.SCHEDULED, nullable=False, index=True
    )
    academic_year: Mapped[str] = mapped_column(String(10), nullable=False)
    # Optional cancellation tracking
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    # Relationships
    event_request: Mapped["EventRequest"] = relationship("EventRequest", back_populates="event")
    approved_version: Mapped["EventRequestVersion"] = relationship(
        "EventRequestVersion", foreign_keys=[approved_version_id]
    )
    club: Mapped["Club"] = relationship("Club")
    hall: Mapped["Hall | None"] = relationship("Hall")
    post_event_report: Mapped["PostEventReport | None"] = relationship(
        "PostEventReport", back_populates="event", uselist=False, cascade="all, delete-orphan"
    )
    actual_expenses: Mapped[list["ActualExpense"]] = relationship(
        "ActualExpense", back_populates="event", cascade="all, delete-orphan"
    )
    cash_advance: Mapped["CashAdvance | None"] = relationship(
        "CashAdvance", back_populates="event", uselist=False, cascade="all, delete-orphan"
    )
    actual_incomes: Mapped[list["ActualIncome"]] = relationship(
        "ActualIncome", back_populates="event", cascade="all, delete-orphan"
    )
    financial_settlement: Mapped["FinancialSettlement | None"] = relationship(
        "FinancialSettlement", back_populates="event", uselist=False, cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_events_club_id_status", "club_id", "status"),
        Index("ix_events_academic_year_status", "academic_year", "status"),
        Index("ix_events_event_date", "event_date"),
    )

    def __repr__(self) -> str:
        return f"<Event id={self.id} title={self.title!r} status={self.status}>"


# ============================================================================
# NOTIFICATION
# ============================================================================


class Notification(Base, UUIDPrimaryKeyMixin):
    """
    In-app notification. Notification creation must not block main transactions.
    Notifications are best-effort in Phase 1.
    """

    __tablename__ = "notifications"

    recipient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("event_requests.id", ondelete="SET NULL"), nullable=True
    )
    notification_type: Mapped[NotificationType] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    recipient: Mapped["User"] = relationship("User", back_populates="notifications")
    event_request: Mapped["EventRequest | None"] = relationship(
        "EventRequest", back_populates="notifications"
    )

    __table_args__ = (
        Index("ix_notifications_recipient_is_read", "recipient_id", "is_read"),
        Index("ix_notifications_created_at", "created_at"),
    )


# ============================================================================
# AUDIT LOG
# ============================================================================


class AuditLog(Base, UUIDPrimaryKeyMixin):
    """
    Append-only audit trail for institutional accountability.
    Never modified or deleted after creation.
    The application DB user must NOT have UPDATE/DELETE privileges on this table.

    actor_email and actor_role are stored as snapshots because:
    - User may be deleted (soft or hard) in the future
    - Role may change — audit must reflect what role was at the time of action
    """

    __tablename__ = "audit_logs"

    # Actor (nullable for system-initiated actions)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Snapshot at time of action (do not rely on joins for audit display)
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Action
    action: Mapped[AuditAction] = mapped_column(String(60), nullable=False)
    # What was acted upon
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # State change (JSONB for flexibility — schema may differ per entity type)
    previous_state: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    new_state: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Request context
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_audit_logs_actor_id", "actor_id"),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_action", "action"),
        Index("ix_audit_logs_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog action={self.action} entity={self.entity_type}/{self.entity_id}>"


# ============================================================================
# IDEMPOTENCY RECORD
# ============================================================================


class IdempotencyRecord(Base, UUIDPrimaryKeyMixin):
    """
    Stores idempotency keys for submission endpoints.
    Duplicate requests with the same key return the cached response.
    Records expire after configured TTL (default 24 hours).
    """

    __tablename__ = "idempotency_records"

    idempotency_key: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True
    )
    endpoint: Mapped[str] = mapped_column(String(500), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (Index("ix_idempotency_records_expires_at", "expires_at"),)


# ============================================================================
# POST-EVENT REPORT (PHASE 2.1)
# ============================================================================


class PostEventReport(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Post-event execution report submitted by Club Secretary and certified by Faculty Advisor.
    Preserves revision tracking and immutable snapshot history.
    """

    __tablename__ = "post_event_reports"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    revision_number: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    actual_attendance: Mapped[int] = mapped_column(Integer, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    objectives_achieved: Mapped[str] = mapped_column(Text, nullable=False)
    outcomes: Mapped[str | None] = mapped_column(Text, nullable=True)
    challenges: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[PostEventReportStatus] = mapped_column(
        String(30), default=PostEventReportStatus.SUBMITTED, nullable=False, index=True
    )
    submitted_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    certified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    certified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    certification_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    event: Mapped["Event"] = relationship("Event", back_populates="post_event_report")
    submitter: Mapped["User"] = relationship("User", foreign_keys=[submitted_by])
    certifier: Mapped["User"] = relationship("User", foreign_keys=[certified_by])

    __table_args__ = (
        CheckConstraint("actual_attendance > 0", name="ck_post_event_reports_attendance_positive"),
        CheckConstraint("revision_number >= 1", name="ck_post_event_reports_revision_positive"),
    )


# ============================================================================
# ACTUAL EXPENSES (PHASE 2.2)
# ============================================================================


class ActualExpense(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Auditable actual expenditure line item for a COMPLETED event.
    Claimed amount > 0, Verified amount in [0, claimed_amount].
    Disallowed amount is dynamically derived (never persisted redundantly).
    """

    __tablename__ = "actual_expenses"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    budget_line_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("budget_line_items.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    category: Mapped[BudgetLineItemCategory] = mapped_column(String(30), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    vendor_name: Mapped[str] = mapped_column(String(255), nullable=False)
    vendor_gstin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    claimed_amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), nullable=False
    )
    verified_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=12, scale=2), nullable=True
    )
    status: Mapped[ActualExpenseStatus] = mapped_column(
        String(30), default=ActualExpenseStatus.DRAFT, nullable=False, index=True
    )
    bill_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    submitted_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finance_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    query_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_flagged_for_review: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    review_notes: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Relationships
    event: Mapped["Event"] = relationship("Event", back_populates="actual_expenses")
    bill_document: Mapped["Document"] = relationship(
        "Document", foreign_keys=[bill_document_id], back_populates="actual_expenses"
    )
    budget_line_item: Mapped["BudgetLineItem | None"] = relationship("BudgetLineItem")
    submitter: Mapped["User"] = relationship("User", foreign_keys=[submitted_by])
    verifier: Mapped["User | None"] = relationship("User", foreign_keys=[verified_by])

    @property
    def disallowed_amount(self) -> Decimal:
        if self.status in (
            ActualExpenseStatus.VERIFIED,
            ActualExpenseStatus.PARTIALLY_VERIFIED,
            ActualExpenseStatus.DISALLOWED,
        ):
            v = self.verified_amount if self.verified_amount is not None else Decimal("0.00")
            return max(Decimal("0.00"), self.claimed_amount - v)
        return Decimal("0.00")

    __table_args__ = (
        CheckConstraint("claimed_amount > 0.00", name="chk_actual_expenses_claimed_positive"),
        CheckConstraint(
            "verified_amount IS NULL OR verified_amount >= 0.00",
            name="chk_actual_expenses_verified_non_negative",
        ),
        CheckConstraint(
            "verified_amount IS NULL OR verified_amount <= claimed_amount",
            name="chk_actual_expenses_verified_le_claimed",
        ),
    )

# ============================================================================
# PHASE 2.3 FINANCIAL SETTLEMENT, CASH ADVANCE & ACTUAL INCOME MODELS
# ============================================================================


class CashAdvance(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Cash advance requisition and disbursement for a confirmed event.
    Phase 2.3 Rule: At most one advance record per event (1:0..1).
    Constraint: 0 <= amount_disbursed <= amount_approved.
    Disbursed amount ceiling (<= sanctioned_grant) is enforced at the service layer.
    """

    __tablename__ = "cash_advances"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    amount_requested: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), nullable=False
    )
    amount_approved: Mapped[Decimal | None] = mapped_column(
        Numeric(precision=12, scale=2), nullable=True
    )
    amount_disbursed: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), default=Decimal("0.00"), nullable=False
    )
    status: Mapped[CashAdvanceStatus] = mapped_column(
        String(20), default=CashAdvanceStatus.REQUESTED, nullable=False, index=True
    )
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    disbursed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    disbursement_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    payment_reference: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    event: Mapped["Event"] = relationship("Event", back_populates="cash_advance")
    recipient: Mapped["User"] = relationship("User", foreign_keys=[recipient_id])
    approver: Mapped["User | None"] = relationship("User", foreign_keys=[approved_by])
    disburser: Mapped["User | None"] = relationship("User", foreign_keys=[disbursed_by])

    __table_args__ = (
        CheckConstraint("amount_requested > 0.00", name="chk_cash_advances_requested_positive"),
        CheckConstraint(
            "amount_approved IS NULL OR amount_approved >= 0.00",
            name="chk_cash_advances_approved_non_negative",
        ),
        CheckConstraint(
            "amount_disbursed >= 0.00",
            name="chk_cash_advances_disbursed_non_negative",
        ),
        CheckConstraint(
            "amount_approved IS NULL OR amount_disbursed <= amount_approved",
            name="chk_cash_advances_disbursed_le_approved",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<CashAdvance id={self.id} event_id={self.event_id} "
            f"status={self.status} disbursed={self.amount_disbursed}>"
        )


class ActualIncome(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Self-generated revenue record for an event (registration fees, sponsorships, etc.).
    Phase 2.3: Every income entry requires supporting document evidence.
    Document type: DocumentType.INCOME_EVIDENCE.
    Only VERIFIED income contributes to settlement actual income (I_actual).
    """

    __tablename__ = "actual_incomes"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[IncomeSourceType] = mapped_column(
        String(30), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    payer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), nullable=False
    )
    received_date: Mapped[date] = mapped_column(Date, nullable=False)
    reference_number: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    evidence_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True
    )
    status: Mapped[ActualIncomeStatus] = mapped_column(
        String(20), default=ActualIncomeStatus.RECORDED, nullable=False, index=True
    )
    recorded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    verified_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finance_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    event: Mapped["Event"] = relationship("Event", back_populates="actual_incomes")
    evidence_document: Mapped["Document"] = relationship(
        "Document", foreign_keys=[evidence_document_id], back_populates="actual_incomes"
    )
    recorder: Mapped["User"] = relationship("User", foreign_keys=[recorded_by])
    verifier: Mapped["User | None"] = relationship("User", foreign_keys=[verified_by])

    __table_args__ = (
        CheckConstraint("amount > 0.00", name="chk_actual_incomes_amount_positive"),
        Index("ix_actual_incomes_event_id_status", "event_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<ActualIncome id={self.id} event_id={self.event_id} "
            f"amount={self.amount} status={self.status}>"
        )


class FinancialSettlement(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Final institutional reconciliation and settlement for a completed event.
    Snapshots sanctioned financial values and locks server-authoritative calculations.
    Relationship: Event 1 : 1 FinancialSettlement (unique event_id).
    """

    __tablename__ = "financial_settlements"

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    approved_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("event_request_versions.id"), nullable=False
    )

    # Immutable Financial Snapshots captured at settlement preparation
    sanctioned_grant: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), nullable=False
    )
    sanctioned_expenditure: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), nullable=False
    )
    expected_income: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), default=Decimal("0.00"), nullable=False
    )

    # Calculated Snapshot Values (Server Authoritative)
    total_claimed_expenditure: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), default=Decimal("0.00"), nullable=False
    )
    total_verified_expenditure: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), default=Decimal("0.00"), nullable=False
    )
    total_disallowed_expenditure: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), default=Decimal("0.00"), nullable=False
    )
    total_verified_income: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), default=Decimal("0.00"), nullable=False
    )
    net_deficit: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), default=Decimal("0.00"), nullable=False
    )
    institutional_payout: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), default=Decimal("0.00"), nullable=False
    )
    cash_advance_disbursed: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), default=Decimal("0.00"), nullable=False
    )
    settlement_balance: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), default=Decimal("0.00"), nullable=False
    )
    reimbursement_due: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), default=Decimal("0.00"), nullable=False
    )
    refund_due: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), default=Decimal("0.00"), nullable=False
    )
    settlement_type: Mapped[SettlementType] = mapped_column(
        String(30), nullable=False
    )
    status: Mapped[SettlementStatus] = mapped_column(
        String(30), default=SettlementStatus.DRAFT, nullable=False, index=True
    )

    # Audit / Operational Tracking
    prepared_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    audited_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    audited_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finance_remarks: Mapped[str | None] = mapped_column(Text, nullable=True)
    query_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    event: Mapped["Event"] = relationship("Event", back_populates="financial_settlement")
    approved_version: Mapped["EventRequestVersion"] = relationship(
        "EventRequestVersion", foreign_keys=[approved_version_id]
    )
    preparer: Mapped["User"] = relationship("User", foreign_keys=[prepared_by])
    auditor: Mapped["User | None"] = relationship("User", foreign_keys=[audited_by])
    payments: Mapped[list["SettlementPayment"]] = relationship(
        "SettlementPayment",
        back_populates="settlement",
        cascade="all, delete-orphan",
        order_by="SettlementPayment.created_at",
    )
    revisions: Mapped[list["SettlementRevision"]] = relationship(
        "SettlementRevision",
        back_populates="settlement",
        cascade="all, delete-orphan",
        order_by="SettlementRevision.revision_number",
    )

    __table_args__ = (
        CheckConstraint("sanctioned_grant >= 0.00", name="chk_fin_settlements_grant_non_negative"),
        CheckConstraint(
            "sanctioned_expenditure >= 0.00",
            name="chk_fin_settlements_exp_non_negative",
        ),
        CheckConstraint(
            "total_verified_expenditure >= 0.00",
            name="chk_fin_settlements_v_exp_non_negative",
        ),
        CheckConstraint(
            "total_verified_income >= 0.00",
            name="chk_fin_settlements_v_inc_non_negative",
        ),
        CheckConstraint(
            "institutional_payout >= 0.00",
            name="chk_fin_settlements_payout_non_negative",
        ),
        CheckConstraint(
            "cash_advance_disbursed >= 0.00",
            name="chk_fin_settlements_advance_non_negative",
        ),
        CheckConstraint(
            "reimbursement_due >= 0.00",
            name="chk_fin_settlements_reimb_non_negative",
        ),
        CheckConstraint(
            "refund_due >= 0.00",
            name="chk_fin_settlements_refund_non_negative",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<FinancialSettlement id={self.id} event_id={self.event_id} "
            f"status={self.status} balance={self.settlement_balance}>"
        )


class SettlementPayment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """
    Record of an actual financial payment/receipt against a financial settlement.
    Types: REIMBURSEMENT_DISBURSEMENT (College -> Club) or ADVANCE_REFUND_RECEIPT (Club -> College).
    Proof document is mandatory (DocumentType.SETTLEMENT_PAYMENT_PROOF).
    """

    __tablename__ = "settlement_payments"

    settlement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("financial_settlements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    payment_type: Mapped[SettlementPaymentType] = mapped_column(
        String(30), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=2), nullable=False
    )
    payment_method: Mapped[PaymentMethod] = mapped_column(
        String(30), nullable=False
    )
    transaction_reference: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    proof_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False, index=True
    )
    recorded_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    settlement: Mapped["FinancialSettlement"] = relationship(
        "FinancialSettlement", back_populates="payments"
    )
    proof_document: Mapped["Document"] = relationship(
        "Document", foreign_keys=[proof_document_id], back_populates="settlement_payments"
    )
    recorder: Mapped["User"] = relationship("User", foreign_keys=[recorded_by])

    __table_args__ = (
        CheckConstraint("amount > 0.00", name="chk_settlement_payments_amount_positive"),
    )

    def __repr__(self) -> str:
        return (
            f"<SettlementPayment id={self.id} settlement_id={self.settlement_id} "
            f"type={self.payment_type} amount={self.amount}>"
        )


class SettlementRevision(Base, UUIDPrimaryKeyMixin):
    """
    Immutable audit snapshot created prior to reopening an approved or
    settled settlement.
    Captures full JSON serialization of the settlement and all associated payments.
    """

    __tablename__ = "settlement_revisions"

    settlement_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("financial_settlements.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_data: Mapped[dict[str, Any]] = mapped_column(
        JSONType, nullable=False
    )
    reopened_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    reopening_reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    settlement: Mapped["FinancialSettlement"] = relationship(
        "FinancialSettlement", back_populates="revisions"
    )
    reopener: Mapped["User"] = relationship("User", foreign_keys=[reopened_by])

    __table_args__ = (
        UniqueConstraint(
            "settlement_id", "revision_number", name="uq_settlement_revisions_number"
        ),
        CheckConstraint(
            "revision_number >= 1", name="chk_settlement_revisions_number_positive"
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<SettlementRevision id={self.id} settlement_id={self.settlement_id} "
            f"rev={self.revision_number}>"
        )
