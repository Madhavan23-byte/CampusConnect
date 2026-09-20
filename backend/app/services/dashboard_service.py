"""
CampusConnect - Dashboard Aggregation Service
Aggregates role-aware metrics respecting RBAC and resource ownership.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.domain import (
    AuditLog,
    Club,
    ClubMember,
    EventRequest,
    User,
    WorkflowInstance,
    WorkflowInstanceStep,
    WorkflowTemplateStep,
)
from app.models.enums import (
    AuditAction,
    ClubMemberRole,
    EventRequestStatus,
    UserRole,
    WorkflowInstanceStatus,
    WorkflowStepStatus,
)
from app.schemas.dashboard import (
    AdminDashboardMetrics,
    DashboardResponse,
    ReviewerDashboardMetrics,
    SecretaryDashboardMetrics,
)


class DashboardService:
    @classmethod
    async def get_dashboard(cls, db: AsyncSession, actor: User) -> DashboardResponse:
        """Return role-aware workflow and system metrics."""
        role_str = actor.role.value if hasattr(actor.role, "value") else str(actor.role)
        resp = DashboardResponse(role=role_str, user_id=actor.id)

        # 1. SYSTEM_ADMIN
        if actor.role == UserRole.SYSTEM_ADMIN:
            total_users = (
                await db.scalar(
                    select(func.count()).select_from(User).where(User.deleted_at.is_(None))
                )
                or 0
            )
            active_users = (
                await db.scalar(
                    select(func.count())
                    .select_from(User)
                    .where(User.is_active.is_(True), User.deleted_at.is_(None))
                )
                or 0
            )
            total_clubs = (
                await db.scalar(
                    select(func.count()).select_from(Club).where(Club.deleted_at.is_(None))
                )
                or 0
            )
            total_events = (
                await db.scalar(
                    select(func.count())
                    .select_from(EventRequest)
                    .where(EventRequest.deleted_at.is_(None))
                )
                or 0
            )

            pending_proposals = (
                await db.scalar(
                    select(func.count())
                    .select_from(EventRequest)
                    .where(
                        EventRequest.status.in_(
                            [EventRequestStatus.SUBMITTED, EventRequestStatus.IN_REVIEW]
                        ),
                        EventRequest.deleted_at.is_(None),
                    )
                )
                or 0
            )

            audit_stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(10)
            audit_logs = list((await db.scalars(audit_stmt)).all())
            recent_activity = [
                {
                    "action": log.action.value if hasattr(log.action, "value") else str(log.action),
                    "actor_email": log.actor_email,
                    "entity_type": log.entity_type,
                    "entity_id": log.entity_id,
                    "created_at": log.created_at.isoformat() if log.created_at else None,
                }
                for log in audit_logs
            ]

            resp.admin = AdminDashboardMetrics(
                system_counts={
                    "total_users": total_users,
                    "total_clubs": total_clubs,
                    "total_events": total_events,
                },
                pending_proposals=pending_proposals,
                active_users=active_users,
                recent_activity=recent_activity,
            )
            return resp

        # 2. CLUB_SECRETARY
        if actor.role == UserRole.CLUB_SECRETARY:
            club_ids_stmt = select(ClubMember.club_id).where(
                ClubMember.user_id == actor.id,
                ClubMember.member_role == ClubMemberRole.SECRETARY,
                ClubMember.is_active.is_(True),
            )
            secretary_club_ids = list((await db.scalars(club_ids_stmt)).all())

            # Count by status for proposals belonging to secretary's clubs or submitted by actor
            filter_clause = (
                EventRequest.club_id.in_(secretary_club_ids)
                if secretary_club_ids
                else EventRequest.submitted_by == actor.id
            )

            async def count_status(status_val: EventRequestStatus) -> int:
                stmt = (
                    select(func.count())
                    .select_from(EventRequest)
                    .where(
                        filter_clause,
                        EventRequest.status == status_val,
                        EventRequest.deleted_at.is_(None),
                    )
                )
                return (await db.scalar(stmt)) or 0

            draft_cnt = await count_status(EventRequestStatus.DRAFT)
            sub_cnt = await count_status(EventRequestStatus.SUBMITTED)
            in_rev_cnt = await count_status(EventRequestStatus.IN_REVIEW)
            rev_req_cnt = await count_status(EventRequestStatus.REVISION_REQUIRED)
            app_cnt = await count_status(EventRequestStatus.APPROVED)
            rej_cnt = await count_status(EventRequestStatus.REJECTED)

            events_stmt = (
                select(EventRequest)
                .options(selectinload(EventRequest.club))
                .where(filter_clause, EventRequest.deleted_at.is_(None))
                .order_by(EventRequest.created_at.desc())
                .limit(10)
            )
            events = list((await db.scalars(events_stmt)).all())
            recent_events = [
                {
                    "id": str(ev.id),
                    "title": ev.title,
                    "status": ev.status.value if hasattr(ev.status, "value") else str(ev.status),
                    "club_id": str(ev.club_id),
                    "club_name": ev.club.name if ev.club else None,
                    "created_at": ev.created_at.isoformat() if ev.created_at else None,
                }
                for ev in events
            ]

            resp.secretary = SecretaryDashboardMetrics(
                draft_count=draft_cnt,
                submitted_count=sub_cnt,
                in_review_count=in_rev_cnt,
                revision_required_count=rev_req_cnt,
                approved_count=app_cnt,
                rejected_count=rej_cnt,
                recent_events=recent_events,
            )
            return resp

        # 3. REVIEWER ROLES (FACULTY_ADVISOR, HALL_INCHARGE, FINANCE_OFFICER, UNION, DEAN, etc.)
        # Pending actions: step is PENDING, step_order == current_step_order
        # and user is either directly assigned or matches required_role
        pending_stmt = (
            select(func.count())
            .select_from(WorkflowInstanceStep)
            .join(WorkflowInstance, WorkflowInstanceStep.instance_id == WorkflowInstance.id)
            .join(
                WorkflowTemplateStep,
                WorkflowInstanceStep.template_step_id == WorkflowTemplateStep.id,
            )
            .where(
                WorkflowInstanceStep.status == WorkflowStepStatus.PENDING,
                WorkflowInstanceStep.step_order == WorkflowInstance.current_step_order,
                WorkflowInstance.status == WorkflowInstanceStatus.IN_PROGRESS,
                (
                    (WorkflowInstanceStep.assigned_to == actor.id)
                    if actor.role == UserRole.FACULTY_ADVISOR
                    else (
                        (WorkflowInstanceStep.assigned_to == actor.id)
                        | (WorkflowTemplateStep.required_role == actor.role)
                    )
                ),
            )
        )
        pending_cnt = await db.scalar(pending_stmt) or 0

        completed_stmt = (
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.actor_id == actor.id,
                AuditLog.action == AuditAction.PROPOSAL_APPROVED,
                AuditLog.entity_type == "workflow_step",
            )
        )
        completed_cnt = await db.scalar(completed_stmt) or 0

        recent_act_stmt = (
            select(AuditLog)
            .where(AuditLog.actor_id == actor.id)
            .order_by(AuditLog.created_at.desc())
            .limit(10)
        )
        acts = list((await db.scalars(recent_act_stmt)).all())
        recent_workflow_activity = [
            {
                "action": a.action.value if hasattr(a.action, "value") else str(a.action),
                "entity_type": a.entity_type,
                "entity_id": a.entity_id,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in acts
        ]

        resp.reviewer = ReviewerDashboardMetrics(
            pending_actions=pending_cnt,
            completed_approvals=completed_cnt,
            recent_workflow_activity=recent_workflow_activity,
        )
        return resp
