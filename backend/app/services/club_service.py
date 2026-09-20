"""
CampusConnect Backend — Club Governance Service

Encapsulates all domain logic for college club management:
1. Club creation:
   - Validates faculty advisor existence, active status, and FACULTY_ADVISOR role
   - Normalizes club name and generates deterministic URL-safe slugs
   - Safe slug collision handling
   - Database constraint race-condition protection (IntegrityError -> 409 Conflict)
   - Created-by binding to authenticated user
   - Transactionally consistent audit logging (CLUB_CREATED, ADVISOR_ASSIGNED)
2. Club retrieval & listing:
   - Safe filtering excluding soft-deleted clubs
   - Pagination support
   - Eager-loading of relational data (faculty advisor, member counts)
3. Club updates:
   - Strict resource ownership verification (SYSTEM_ADMIN or active SECRETARY of specific club)
   - Cross-club tampering prevention (raises ResourceOwnershipError -> 403 Forbidden)
   - Faculty advisor update validation and audit logging (ADVISOR_ASSIGNED)
   - Name uniqueness checks and slug regeneration
   - Transactionally consistent audit logging (CLUB_UPDATED)
4. Membership management:
   - Resource ownership verification
   - Target user validation (existence, active status)
   - Duplicate active membership prevention with unique constraint safety
   - Soft deactivation (is_active=False) preserving institutional history
   - Membership reactivation support
   - Transactionally consistent audit logging (MEMBER_ADDED, MEMBER_REMOVED)
"""

import re
import unicodedata
import uuid
from typing import Any

from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.base import NO_VALUE

from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ResourceOwnershipError,
)
from app.models.domain import AuditLog, Club, ClubMember, User
from app.models.enums import AuditAction, ClubMemberRole, UserRole
from app.schemas.club import (
    ClubCreate,
    ClubMemberAdd,
    ClubMemberResponse,
    ClubMemberUpdate,
    ClubResponse,
    ClubUpdate,
)


def slugify(text: str) -> str:
    """
    Generate a deterministic, URL-safe slug from a string.
    Lowercases, removes special characters, and hyphenates spaces.
    """
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    slug = text.strip("-")
    return slug[:80] or "club"


def to_club_response(club: Club, member_count: int | None = None) -> ClubResponse:
    """Format a Club domain model into a safe public ClubResponse schema without triggering lazy loads."""
    insp = inspect(club)
    advisor_name = None
    advisor_email = None
    if "faculty_advisor" in insp.attrs:
        adv = insp.attrs.faculty_advisor.loaded_value
        if adv is not NO_VALUE and adv is not None:
            advisor_name = adv.full_name
            advisor_email = adv.email

    count = member_count
    if count is None and "members" in insp.attrs:
        mems = insp.attrs.members.loaded_value
        if mems is not NO_VALUE and mems is not None:
            count = sum(1 for m in mems if m.is_active)

    return ClubResponse(
        id=club.id,
        name=club.name,
        slug=club.slug,
        description=club.description,
        faculty_advisor_id=club.faculty_advisor_id,
        faculty_advisor_name=advisor_name,
        faculty_advisor_email=advisor_email,
        academic_year=club.academic_year,
        is_active=club.is_active,
        logo_url=club.logo_url,
        created_by=club.created_by,
        created_at=club.created_at,
        updated_at=club.updated_at,
        member_count=count,
    )


def to_member_response(member: ClubMember) -> ClubMemberResponse:
    """Format a ClubMember model into a safe public ClubMemberResponse schema without triggering lazy loads."""
    insp = inspect(member)
    user_name = None
    user_email = None
    if "user" in insp.attrs:
        u = insp.attrs.user.loaded_value
        if u is not NO_VALUE and u is not None:
            user_name = u.full_name
            user_email = u.email

    return ClubMemberResponse(
        id=member.id,
        club_id=member.club_id,
        user_id=member.user_id,
        user_full_name=user_name,
        user_email=user_email,
        member_role=member.member_role,
        is_active=member.is_active,
        joined_at=member.joined_at,
    )


class ClubService:
    """Domain service managing club governance lifecycle, membership, and audits."""

    @staticmethod
    async def generate_unique_slug(
        db: AsyncSession, base_name: str, exclude_club_id: uuid.UUID | None = None
    ) -> str:
        """
        Generate a unique, URL-safe slug for a club.
        Appends incremental numerical suffixes (-2, -3, ...) if collisions exist.
        """
        base_slug = slugify(base_name)
        candidate = base_slug
        counter = 1

        # Check existing slugs (including soft-deleted to respect DB unique index)
        while True:
            stmt = select(Club).where(Club.slug == candidate)
            if exclude_club_id:
                stmt = stmt.where(Club.id != exclude_club_id)
            existing = await db.scalar(stmt)
            if not existing:
                return candidate
            counter += 1
            candidate = f"{base_slug}-{counter}"

    @staticmethod
    async def validate_faculty_advisor(db: AsyncSession, advisor_id: uuid.UUID) -> User:
        """
        Ensure the target faculty advisor exists, is active, and possesses UserRole.FACULTY_ADVISOR.
        """
        user = await db.scalar(select(User).where(User.id == advisor_id))
        if not user or user.deleted_at is not None:
            raise BadRequestError(f"Faculty advisor with ID '{advisor_id}' was not found.")

        if not user.is_active:
            raise BadRequestError("Assigned faculty advisor account is inactive.")

        user_role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
        if user_role_str != UserRole.FACULTY_ADVISOR.value:
            raise BadRequestError(
                f"User '{user.email}' has role '{user_role_str}', but FACULTY_ADVISOR is required."
            )

        return user

    @staticmethod
    async def verify_club_ownership(
        db: AsyncSession,
        club_id: uuid.UUID,
        actor: User,
        action_description: str = "manage this club",
    ) -> Club:
        """
        Enforce resource ownership:
        1. Club must exist and not be soft-deleted (raises NotFoundError -> 404).
        2. SYSTEM_ADMIN is granted institutional governance access.
        3. CLUB_SECRETARY is authorized ONLY IF they hold an active SECRETARY membership
           record for THIS specific club.
        4. Cross-club access or non-ownership raises ResourceOwnershipError -> 403.
        """
        stmt = (
            select(Club)
            .options(selectinload(Club.faculty_advisor))
            .where(Club.id == club_id, Club.deleted_at.is_(None))
        )
        club = await db.scalar(stmt)
        if not club:
            raise NotFoundError(f"Club with ID '{club_id}' not found.")

        actor_role = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        if actor_role == UserRole.SYSTEM_ADMIN.value:
            return club

        if actor_role == UserRole.CLUB_SECRETARY.value:
            membership_stmt = select(ClubMember).where(
                ClubMember.club_id == club_id,
                ClubMember.user_id == actor.id,
                ClubMember.member_role == ClubMemberRole.SECRETARY,
                ClubMember.is_active.is_(True),
            )
            membership = await db.scalar(membership_stmt)
            if not membership:
                raise ResourceOwnershipError(
                    f"Access denied: You are not an active secretary of club '{club.name}' to {action_description}."
                )
            return club

        raise ForbiddenError(f"User role '{actor_role}' is not authorized to {action_description}.")

    @classmethod
    async def create_club(
        cls,
        db: AsyncSession,
        club_in: ClubCreate,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Club:
        """
        Create a new college club charter with audit logging.
        Validates advisor, checks name uniqueness, generates slug, and enforces DB integrity.
        """
        name = " ".join(club_in.name.strip().split())

        # Check duplicate active club name
        existing_name = await db.scalar(
            select(Club).where(func.lower(Club.name) == func.lower(name), Club.deleted_at.is_(None))
        )
        if existing_name:
            raise ConflictError(f"A club with name '{name}' already exists.")

        # Validate faculty advisor if provided
        advisor: User | None = None
        if club_in.faculty_advisor_id:
            advisor = await cls.validate_faculty_advisor(db, club_in.faculty_advisor_id)

        # Generate unique URL-safe slug
        slug = await cls.generate_unique_slug(db, name)

        club_id = uuid.uuid4()
        club = Club(
            id=club_id,
            name=name,
            slug=slug,
            description=club_in.description,
            faculty_advisor_id=club_in.faculty_advisor_id,
            academic_year=club_in.academic_year,
            logo_url=club_in.logo_url,
            is_active=True,
            created_by=actor.id,
        )
        db.add(club)

        # Transactional audit log: CLUB_CREATED
        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        new_state_snapshot = {
            "name": club.name,
            "slug": club.slug,
            "academic_year": club.academic_year,
            "faculty_advisor_id": str(club.faculty_advisor_id) if club.faculty_advisor_id else None,
            "description": club.description,
            "logo_url": club.logo_url,
            "is_active": club.is_active,
        }
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.CLUB_CREATED,
                entity_type="club",
                entity_id=str(club.id),
                previous_state=None,
                new_state=new_state_snapshot,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        # Audit log for advisor assignment if assigned at creation
        if advisor:
            db.add(
                AuditLog(
                    actor_id=actor.id,
                    actor_email=actor.email,
                    actor_role=actor_role_str,
                    action=AuditAction.ADVISOR_ASSIGNED,
                    entity_type="club",
                    entity_id=str(club.id),
                    previous_state=None,
                    new_state={
                        "faculty_advisor_id": str(advisor.id),
                        "faculty_advisor_email": advisor.email,
                    },
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
            )

        try:
            await db.commit()
            await db.refresh(club)
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictError(
                "A club with this name or slug already exists in the system."
            ) from exc

        # Eagerly load advisor relationship for serialization
        club_loaded = await db.scalar(
            select(Club).options(selectinload(Club.faculty_advisor)).where(Club.id == club.id)
        )
        return club_loaded or club

    @staticmethod
    async def get_club(db: AsyncSession, club_id: uuid.UUID) -> Club:
        """Retrieve an active club by ID. Returns 404 for nonexistent or soft-deleted clubs."""
        stmt = (
            select(Club)
            .options(selectinload(Club.faculty_advisor), selectinload(Club.members))
            .where(Club.id == club_id, Club.deleted_at.is_(None))
        )
        club = await db.scalar(stmt)
        if not club:
            raise NotFoundError(f"Club with ID '{club_id}' not found.")
        return club

    @staticmethod
    async def list_clubs(
        db: AsyncSession,
        skip: int = 0,
        limit: int = 50,
        is_active: bool | None = None,
    ) -> list[Club]:
        """List clubs excluding soft-deleted records. Supports filtering and pagination."""
        stmt = (
            select(Club)
            .options(selectinload(Club.faculty_advisor), selectinload(Club.members))
            .where(Club.deleted_at.is_(None))
        )
        if is_active is not None:
            stmt = stmt.where(Club.is_active.is_(is_active))

        stmt = stmt.order_by(Club.name.asc()).offset(skip).limit(limit)
        result = await db.scalars(stmt)
        return list(result.all())

    @classmethod
    async def update_club(
        cls,
        db: AsyncSession,
        club_id: uuid.UUID,
        club_in: ClubUpdate,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Club:
        """
        Update an existing club's profile. Enforces resource ownership and audit trail.
        """
        club = await cls.verify_club_ownership(db, club_id, actor, "update club profile")

        prev_state: dict[str, Any] = {
            "name": club.name,
            "slug": club.slug,
            "description": club.description,
            "faculty_advisor_id": str(club.faculty_advisor_id) if club.faculty_advisor_id else None,
            "academic_year": club.academic_year,
            "is_active": club.is_active,
            "logo_url": club.logo_url,
        }

        advisor_assigned = False
        new_advisor: User | None = None

        if (
            club_in.faculty_advisor_id is not None
            and club_in.faculty_advisor_id != club.faculty_advisor_id
        ):
            new_advisor = await cls.validate_faculty_advisor(db, club_in.faculty_advisor_id)
            club.faculty_advisor_id = new_advisor.id
            advisor_assigned = True

        if club_in.name is not None and club_in.name != club.name:
            cleaned_name = " ".join(club_in.name.strip().split())
            duplicate = await db.scalar(
                select(Club).where(
                    func.lower(Club.name) == func.lower(cleaned_name),
                    Club.id != club_id,
                    Club.deleted_at.is_(None),
                )
            )
            if duplicate:
                raise ConflictError(f"A club with name '{cleaned_name}' already exists.")

            club.name = cleaned_name
            club.slug = await cls.generate_unique_slug(db, cleaned_name, exclude_club_id=club_id)

        if club_in.description is not None:
            club.description = club_in.description
        if club_in.academic_year is not None:
            club.academic_year = club_in.academic_year
        if club_in.is_active is not None:
            club.is_active = club_in.is_active
        if club_in.logo_url is not None:
            club.logo_url = club_in.logo_url

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        new_state: dict[str, Any] = {
            "name": club.name,
            "slug": club.slug,
            "description": club.description,
            "faculty_advisor_id": str(club.faculty_advisor_id) if club.faculty_advisor_id else None,
            "academic_year": club.academic_year,
            "is_active": club.is_active,
            "logo_url": club.logo_url,
        }

        # Audit log for club profile update
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.CLUB_UPDATED,
                entity_type="club",
                entity_id=str(club.id),
                previous_state=prev_state,
                new_state=new_state,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        # Separate audit event if advisor changed
        if advisor_assigned and new_advisor:
            db.add(
                AuditLog(
                    actor_id=actor.id,
                    actor_email=actor.email,
                    actor_role=actor_role_str,
                    action=AuditAction.ADVISOR_ASSIGNED,
                    entity_type="club",
                    entity_id=str(club.id),
                    previous_state={"faculty_advisor_id": prev_state["faculty_advisor_id"]},
                    new_state={
                        "faculty_advisor_id": str(new_advisor.id),
                        "faculty_advisor_email": new_advisor.email,
                    },
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
            )

        try:
            await db.commit()
            await db.refresh(club)
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictError("A club with this name or slug already exists.") from exc

        # Reload with relationships
        club_loaded = await db.scalar(
            select(Club)
            .options(selectinload(Club.faculty_advisor), selectinload(Club.members))
            .where(Club.id == club.id)
        )
        return club_loaded or club

    @classmethod
    async def add_member(
        cls,
        db: AsyncSession,
        club_id: uuid.UUID,
        member_in: ClubMemberAdd,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ClubMember:
        """
        Enroll a user into a club roster with specified role.
        Enforces resource ownership, active status, uniqueness, and audit logs.
        """
        club = await cls.verify_club_ownership(db, club_id, actor, "add members")

        target_user = await db.scalar(select(User).where(User.id == member_in.user_id))
        if not target_user or target_user.deleted_at is not None:
            raise NotFoundError(f"User with ID '{member_in.user_id}' not found.")

        if not target_user.is_active:
            raise BadRequestError("Target user account is inactive and cannot be enrolled.")

        # Check existing membership
        existing_stmt = select(ClubMember).where(
            ClubMember.club_id == club_id, ClubMember.user_id == member_in.user_id
        )
        existing = await db.scalar(existing_stmt)

        if existing:
            if existing.is_active:
                raise ConflictError(
                    f"User '{target_user.email}' is already an active member of this club."
                )
            # Reactivate soft-deactivated membership
            existing.is_active = True
            existing.member_role = member_in.member_role
            member = existing
        else:
            member_id = uuid.uuid4()
            member = ClubMember(
                id=member_id,
                club_id=club_id,
                user_id=member_in.user_id,
                member_role=member_in.member_role,
                is_active=True,
            )
            db.add(member)

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.MEMBER_ADDED,
                entity_type="club_member",
                entity_id=str(member.id),
                previous_state=None,
                new_state={
                    "club_id": str(club_id),
                    "user_id": str(target_user.id),
                    "user_email": target_user.email,
                    "member_role": (
                        member_in.member_role.value
                        if hasattr(member_in.member_role, "value")
                        else str(member_in.member_role)
                    ),
                    "is_active": True,
                },
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        try:
            await db.commit()
            await db.refresh(member)
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictError("Membership record conflict for this club and user.") from exc

        # Reload with user relationship
        loaded = await db.scalar(
            select(ClubMember)
            .options(selectinload(ClubMember.user))
            .where(ClubMember.id == member.id)
        )
        return loaded or member

    @classmethod
    async def update_member(
        cls,
        db: AsyncSession,
        club_id: uuid.UUID,
        target_user_id: uuid.UUID,
        member_in: ClubMemberUpdate,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> ClubMember:
        """
        Update an existing club member's role or active status.
        """
        club = await cls.verify_club_ownership(db, club_id, actor, "modify member roles")

        member_stmt = (
            select(ClubMember)
            .options(selectinload(ClubMember.user))
            .where(ClubMember.club_id == club_id, ClubMember.user_id == target_user_id)
        )
        member = await db.scalar(member_stmt)
        if not member:
            raise NotFoundError("Club member record was not found.")

        prev_role_str = (
            member.member_role.value
            if hasattr(member.member_role, "value")
            else str(member.member_role)
        )
        prev_state = {
            "member_role": prev_role_str,
            "is_active": member.is_active,
        }

        if member_in.member_role is not None:
            member.member_role = member_in.member_role
        if member_in.is_active is not None:
            member.is_active = member_in.is_active

        new_role_str = (
            member.member_role.value
            if hasattr(member.member_role, "value")
            else str(member.member_role)
        )
        new_state = {
            "member_role": new_role_str,
            "is_active": member.is_active,
        }

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)

        # Audit action: MEMBER_REMOVED if deactivated, or CLUB_UPDATED / role changed
        action = (
            AuditAction.MEMBER_REMOVED
            if (member_in.is_active is False and prev_state["is_active"] is True)
            else AuditAction.CLUB_UPDATED
        )

        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=action,
                entity_type="club_member",
                entity_id=str(member.id),
                previous_state=prev_state,
                new_state=new_state,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        await db.commit()
        await db.refresh(member)
        return member

    @classmethod
    async def remove_member(
        cls,
        db: AsyncSession,
        club_id: uuid.UUID,
        target_user_id: uuid.UUID,
        actor: User,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """
        Soft-deactivate a member from the club roster, preserving institutional history.
        """
        club = await cls.verify_club_ownership(db, club_id, actor, "remove members")

        member_stmt = select(ClubMember).where(
            ClubMember.club_id == club_id, ClubMember.user_id == target_user_id
        )
        member = await db.scalar(member_stmt)
        if not member:
            raise NotFoundError("Club member record was not found.")

        if not member.is_active:
            # Already deactivated
            return

        member.is_active = False

        actor_role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        db.add(
            AuditLog(
                actor_id=actor.id,
                actor_email=actor.email,
                actor_role=actor_role_str,
                action=AuditAction.MEMBER_REMOVED,
                entity_type="club_member",
                entity_id=str(member.id),
                previous_state={"is_active": True},
                new_state={"is_active": False},
                reason="Member removed by club governance",
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )

        await db.commit()

    @staticmethod
    async def list_members(
        db: AsyncSession, club_id: uuid.UUID, include_inactive: bool = False
    ) -> list[ClubMember]:
        """List members of a club. By default returns active members."""
        club = await db.scalar(select(Club).where(Club.id == club_id, Club.deleted_at.is_(None)))
        if not club:
            raise NotFoundError(f"Club with ID '{club_id}' not found.")

        stmt = (
            select(ClubMember)
            .options(selectinload(ClubMember.user))
            .where(ClubMember.club_id == club_id)
        )
        if not include_inactive:
            stmt = stmt.where(ClubMember.is_active.is_(True))

        stmt = stmt.order_by(ClubMember.joined_at.asc())
        result = await db.scalars(stmt)
        return list(result.all())
