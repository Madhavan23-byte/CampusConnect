"""
CampusConnect — E2E Test Data Seeder & Cleaner (Phase 2.5.4)
Seeds deterministic institutional test users, clubs, and workflow templates
for end-to-end Playwright tests.
"""
import asyncio
import os
import sys
import uuid
from typing import Any

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.domain import (
    Club,
    ClubMember,
    ClubMemberRole,
    Event,
    EventClosure,
    EventClosureRevision,
    EventRequest,
    EventRequestVersion,
    FinancialSettlement,
    HallBookingConfirmed,
    Notification,
    PostEventReport,
    User,
    UserRole,
    VenueRequest,
    WorkflowInstance,
    WorkflowInstanceStep,
)
from app.services.workflow_service import WorkflowService
from sqlalchemy import delete, select, update

E2E_USERS = [
    ("e2e.admin@college.edu", "E2E Administrator", UserRole.SYSTEM_ADMIN),
    ("e2e.sec@college.edu", "E2E Club Secretary", UserRole.CLUB_SECRETARY),
    ("e2e.advisor@college.edu", "E2E Faculty Advisor", UserRole.FACULTY_ADVISOR),
    ("e2e.hall@college.edu", "E2E Hall Incharge", UserRole.HALL_INCHARGE),
    ("e2e.finance@college.edu", "E2E Finance Officer", UserRole.FINANCE_OFFICER),
    ("e2e.union@college.edu", "E2E Union Advisor", UserRole.ADVISOR_STUDENTS_UNION),
    ("e2e.dean@college.edu", "E2E Dean Student Affairs", UserRole.DEAN_STUDENT_AFFAIRS),
    ("e2e.principal@college.edu", "E2E Principal", UserRole.PRINCIPAL),
    ("e2e.other_sec@college.edu", "Other Club Secretary", UserRole.CLUB_SECRETARY),
]

PASSWORD = "Password123!"


async def reset_e2e_events(session) -> None:
    """Safely cleans up any prior E2E event instances without deleting clubs or users."""
    e2e_club_ids = (
        await session.scalars(
            select(Club.id).where(Club.slug.in_(["e2e-coding-society", "e2e-robotics-society"]))
        )
    ).all()

    if e2e_club_ids:
        # Find all event requests for e2e clubs
        event_req_ids = (
            await session.scalars(
                select(EventRequest.id).where(EventRequest.club_id.in_(e2e_club_ids))
            )
        ).all()

        if event_req_ids:
            # Find associated events
            event_ids = (
                await session.scalars(
                    select(Event.id).where(Event.event_request_id.in_(event_req_ids))
                )
            ).all()

            if event_ids:
                await session.execute(
                    delete(EventClosureRevision).where(EventClosureRevision.event_id.in_(event_ids))
                )
                await session.execute(
                    delete(EventClosure).where(EventClosure.event_id.in_(event_ids))
                )
                await session.execute(
                    delete(FinancialSettlement).where(FinancialSettlement.event_id.in_(event_ids))
                )
                await session.execute(
                    delete(PostEventReport).where(PostEventReport.event_id.in_(event_ids))
                )
                await session.execute(
                    delete(HallBookingConfirmed).where(
                        HallBookingConfirmed.event_request_id.in_(event_req_ids)
                    )
                )
                await session.execute(
                    delete(Event).where(Event.id.in_(event_ids))
                )

            await session.execute(
                delete(VenueRequest).where(VenueRequest.event_request_id.in_(event_req_ids))
            )
            await session.execute(
                delete(Notification).where(Notification.event_request_id.in_(event_req_ids))
            )
            await session.execute(
                delete(EventRequestVersion).where(
                    EventRequestVersion.event_request_id.in_(event_req_ids)
                )
            )

            # Break circular foreign key reference before deletion
            await session.execute(
                update(EventRequest)
                .where(EventRequest.id.in_(event_req_ids))
                .values(workflow_instance_id=None)
            )

            # Workflow instances
            wf_inst_ids = (
                await session.scalars(
                    select(WorkflowInstance.id).where(
                        WorkflowInstance.event_request_id.in_(event_req_ids)
                    )
                )
            ).all()
            if wf_inst_ids:
                await session.execute(
                    delete(WorkflowInstanceStep).where(
                        WorkflowInstanceStep.instance_id.in_(wf_inst_ids)
                    )
                )
                await session.execute(
                    delete(WorkflowInstance).where(WorkflowInstance.id.in_(wf_inst_ids))
                )

            await session.execute(
                delete(EventRequest).where(EventRequest.id.in_(event_req_ids))
            )

        await session.commit()
        print("[CLEAN] Cleaned up previous E2E event data.")


async def seed(clean: bool = True) -> None:
    """Seeds deterministic users, clubs, and default workflow template."""
    async with AsyncSessionLocal() as session:
        if clean:
            await reset_e2e_events(session)

        user_map: dict[str, Any] = {}
        pwd_hash = hash_password(PASSWORD)

        for email, name, role in E2E_USERS:
            stmt = select(User).where(User.email == email)
            user = await session.scalar(stmt)
            if not user:
                user = User(
                    id=uuid.uuid4(),
                    email=email,
                    full_name=name,
                    role=role,
                    email_verified=True,
                    is_active=True,
                    password_hash=pwd_hash,
                )
                session.add(user)
                await session.flush()
            else:
                user.password_hash = pwd_hash
                user.is_active = True
                user.email_verified = True
            user_map[email] = user

        # Ensure default workflow template exists
        admin_user = user_map["e2e.admin@college.edu"]
        template = await WorkflowService.ensure_default_template(session, admin_id=admin_user.id)
        print(f"[SUCCESS] Workflow template ensured: {template.id} ({template.name})")

        # Ensure Clubs exist
        clubs_data = [
            (
                "E2E Coding Society",
                "e2e-coding-society",
                user_map["e2e.advisor@college.edu"].id,
                user_map["e2e.sec@college.edu"].id,
            ),
            (
                "E2E Robotics Society",
                "e2e-robotics-society",
                user_map["e2e.advisor@college.edu"].id,
                user_map["e2e.other_sec@college.edu"].id,
            ),
        ]

        for c_name, c_slug, adv_id, sec_id in clubs_data:
            stmt = select(Club).where(Club.slug == c_slug)
            club = await session.scalar(stmt)
            if not club:
                club = Club(
                    id=uuid.uuid4(),
                    name=c_name,
                    slug=c_slug,
                    description=f"Club for {c_name}",
                    faculty_advisor_id=adv_id,
                    academic_year="2025-2026",
                    is_active=True,
                    created_by=admin_user.id,
                )
                session.add(club)
                await session.flush()

            # Ensure Secretary membership
            m_stmt = select(ClubMember).where(
                ClubMember.club_id == club.id, ClubMember.user_id == sec_id
            )
            member = await session.scalar(m_stmt)
            if not member:
                member = ClubMember(
                    id=uuid.uuid4(),
                    club_id=club.id,
                    user_id=sec_id,
                    member_role=ClubMemberRole.SECRETARY,
                    is_active=True,
                )
                session.add(member)

        await session.commit()
        print("[SUCCESS] E2E test data seeded successfully!")


if __name__ == "__main__":
    clean_mode = "--clean" in sys.argv or "--reset" in sys.argv
    asyncio.run(seed(clean=True))
