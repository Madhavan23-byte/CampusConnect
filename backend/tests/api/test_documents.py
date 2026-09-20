"""
CampusConnect - Secure Document Service & API Test Suite
Covers:
- Valid uploads (PDF, PNG, JPEG, DOCX)
- Invalid extensions (.exe, .sh)
- MIME/magic-number spoofing rejection
- Empty & oversized uploads
- Path traversal protection
- State machine guards (DRAFT/REVISION_REQUIRED vs SUBMITTED/APPROVED)
- Document listing
- Authorized downloads (secretary, reviewers, admin)
- Unauthorized downloads (cross-club access rejection)
- Soft deletion & inactive document protection
- Audit trail verification
"""

import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import create_access_token, hash_password
from app.models.domain import (
    AuditLog,
    Club,
    ClubMember,
    Document,
    Hall,
    User,
)
from app.models.enums import (
    AuditAction,
    ClubMemberRole,
    DocumentType,
    UserRole,
)


async def _create_user(db, role: UserRole, prefix: str) -> User:
    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"{prefix}_{uid}@college.edu",
        password_hash=hash_password("Pass123!Secure"),
        full_name=f"Test {role} {uid}",
        role=role,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def _auth_header(user: User) -> dict[str, str]:
    role_str = user.role.value if hasattr(user.role, "value") else str(user.role)
    token = create_access_token(
        subject=user.id,
        role=role_str,
        email=user.email,
    )
    return {"Authorization": f"Bearer {token}"}


async def _create_club_and_advisor(db, name: str, admin: User):
    uid = uuid.uuid4().hex[:6]
    slug = f"{name.lower().replace(' ', '-')}-{uid}"

    advisor = await _create_user(db, UserRole.FACULTY_ADVISOR, f"fa_{uid}")
    secretary = await _create_user(db, UserRole.CLUB_SECRETARY, f"sec_{uid}")

    club = Club(
        name=f"{name} {uid}",
        slug=slug,
        description="A test club",
        academic_year="2026-27",
        is_active=True,
        faculty_advisor_id=advisor.id,
        created_by=admin.id,
    )
    db.add(club)
    await db.commit()
    await db.refresh(club)

    member = ClubMember(
        club_id=club.id,
        user_id=secretary.id,
        member_role=ClubMemberRole.SECRETARY,
        is_active=True,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)

    return club, secretary, advisor


async def _create_test_hall(db) -> Hall:
    uid = uuid.uuid4().hex[:6]
    hall = Hall(
        name=f"Auditorium {uid}",
        capacity=500,
        location="Campus Center",
        available_facilities=["projector", "ac"],
        is_active=True,
    )
    db.add(hall)
    await db.commit()
    await db.refresh(hall)
    return hall


async def _create_draft_event(client: AsyncClient, club: Club, secretary: User) -> str:
    create_res = await client.post(
        "/api/v1/events",
        json={
            "club_id": str(club.id),
            "title": "Document Test Symposium",
            "description": "Event with documents",
            "event_type": "TECHNICAL",
            "expected_attendees": 150,
            "event_date": (datetime.now(UTC) + timedelta(days=20)).isoformat(),
            "academic_year": "2026-27",
        },
        headers=_auth_header(secretary),
    )
    assert create_res.status_code == 201
    return create_res.json()["id"]


# Valid dummy bytes with authentic magic numbers
VALID_PDF_BYTES = (
    b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<\n/Type /Catalog\n>>\n"
    b"endobj\ntrailer\n<<\n/Root 1 0 R\n>>\n%%EOF"
)
VALID_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4"
)
VALID_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xff\xdb"
VALID_DOCX_BYTES = b"PK\x03\x04\x14\x00\x06\x00\x08\x00\x00\x00!\x00dummy_docx_content"


@pytest.mark.asyncio
class TestDocumentService:
    """Comprehensive test suite for document uploading, validation, RBAC, and lifecycle."""

    async def test_01_upload_valid_pdf(self, client: AsyncClient, db_session):
        """Uploading a valid PDF in DRAFT status succeeds with 201 Created."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_doc1")
        club, secretary, _ = await _create_club_and_advisor(db_session, "Doc Club 1", admin)
        event_id = await _create_draft_event(client, club, secretary)

        files = {"file": ("brochure.pdf", io.BytesIO(VALID_PDF_BYTES), "application/pdf")}
        data = {"document_type": DocumentType.EVENT_PLAN.value}
        res = await client.post(
            f"/api/v1/events/{event_id}/documents",
            files=files,
            data=data,
            headers=_auth_header(secretary),
        )
        assert res.status_code == 201
        body = res.json()
        assert body["original_filename"] == "brochure.pdf"
        assert body["document_type"] == "EVENT_PLAN"
        assert body["is_active"] is True
        assert body["file_size_bytes"] == len(VALID_PDF_BYTES)
        # Verify no storage_path or stored_filename leaked
        assert "storage_path" not in body
        assert "stored_filename" not in body

    async def test_02_upload_valid_png(self, client: AsyncClient, db_session):
        """Uploading a valid PNG image succeeds with 201 Created."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_doc2")
        club, secretary, _ = await _create_club_and_advisor(db_session, "Doc Club 2", admin)
        event_id = await _create_draft_event(client, club, secretary)

        files = {"file": ("banner.png", io.BytesIO(VALID_PNG_BYTES), "image/png")}
        res = await client.post(
            f"/api/v1/events/{event_id}/documents",
            files=files,
            headers=_auth_header(secretary),
        )
        assert res.status_code == 201
        assert res.json()["mime_type"] == "image/png"

    async def test_03_upload_valid_jpeg(self, client: AsyncClient, db_session):
        """Uploading a valid JPEG image succeeds with 201 Created."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_doc3")
        club, secretary, _ = await _create_club_and_advisor(db_session, "Doc Club 3", admin)
        event_id = await _create_draft_event(client, club, secretary)

        files = {"file": ("poster.jpg", io.BytesIO(VALID_JPEG_BYTES), "image/jpeg")}
        res = await client.post(
            f"/api/v1/events/{event_id}/documents",
            files=files,
            headers=_auth_header(secretary),
        )
        assert res.status_code == 201

    async def test_04_upload_valid_docx(self, client: AsyncClient, db_session):
        """Uploading a valid DOCX file succeeds with 201 Created."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_doc4")
        club, secretary, _ = await _create_club_and_advisor(db_session, "Doc Club 4", admin)
        event_id = await _create_draft_event(client, club, secretary)

        files = {
            "file": (
                "proposal.docx",
                io.BytesIO(VALID_DOCX_BYTES),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        }
        res = await client.post(
            f"/api/v1/events/{event_id}/documents",
            files=files,
            headers=_auth_header(secretary),
        )
        assert res.status_code == 201

    async def test_05_upload_disallowed_extension(self, client: AsyncClient, db_session):
        """Disallowed extensions (.exe, .sh, .py) are rejected with 400 Bad Request."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_doc5")
        club, secretary, _ = await _create_club_and_advisor(db_session, "Doc Club 5", admin)
        event_id = await _create_draft_event(client, club, secretary)

        files = {
            "file": ("malicious.exe", io.BytesIO(b"MZ\x90\x00binary"), "application/octet-stream")
        }
        res = await client.post(
            f"/api/v1/events/{event_id}/documents",
            files=files,
            headers=_auth_header(secretary),
        )
        assert res.status_code == 400
        assert "not allowed" in res.json().get("message", res.json().get("detail", "")).lower()

    async def test_06_upload_mime_spoofing_rejected(self, client: AsyncClient, db_session):
        """File claiming to be .pdf but without %PDF- magic signature is rejected with 400."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_doc6")
        club, secretary, _ = await _create_club_and_advisor(db_session, "Doc Club 6", admin)
        event_id = await _create_draft_event(client, club, secretary)

        fake_pdf = io.BytesIO(b"<html><script>alert(1)</script></html>")
        files = {"file": ("fake.pdf", fake_pdf, "application/pdf")}
        res = await client.post(
            f"/api/v1/events/{event_id}/documents",
            files=files,
            headers=_auth_header(secretary),
        )
        assert res.status_code == 400
        assert "signature" in res.json().get("message", res.json().get("detail", "")).lower()

    async def test_07_upload_png_mime_spoofing_rejected(self, client: AsyncClient, db_session):
        """File claiming to be .png but without PNG signature is rejected with 400."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_doc7")
        club, secretary, _ = await _create_club_and_advisor(db_session, "Doc Club 7", admin)
        event_id = await _create_draft_event(client, club, secretary)

        fake_png = io.BytesIO(b"NotAPNGImageContentHere")
        files = {"file": ("fake.png", fake_png, "image/png")}
        res = await client.post(
            f"/api/v1/events/{event_id}/documents",
            files=files,
            headers=_auth_header(secretary),
        )
        assert res.status_code == 400

    async def test_08_upload_empty_file_rejected(self, client: AsyncClient, db_session):
        """Empty (0-byte) file upload is rejected with 400 Bad Request."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_doc8")
        club, secretary, _ = await _create_club_and_advisor(db_session, "Doc Club 8", admin)
        event_id = await _create_draft_event(client, club, secretary)

        files = {"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")}
        res = await client.post(
            f"/api/v1/events/{event_id}/documents",
            files=files,
            headers=_auth_header(secretary),
        )
        assert res.status_code == 400

    async def test_09_upload_oversized_file_rejected(self, client: AsyncClient, db_session):
        """Uploading a file exceeding MAX_FILE_SIZE_BYTES is rejected with 400 Bad Request."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_doc9")
        club, secretary, _ = await _create_club_and_advisor(db_session, "Doc Club 9", admin)
        event_id = await _create_draft_event(client, club, secretary)

        # 11MB file with PDF magic header
        oversized = io.BytesIO(b"%PDF-1.4" + b"A" * (11 * 1024 * 1024))
        files = {"file": ("huge.pdf", oversized, "application/pdf")}
        res = await client.post(
            f"/api/v1/events/{event_id}/documents",
            files=files,
            headers=_auth_header(secretary),
        )
        assert res.status_code == 400
        assert "exceeds" in res.json().get("message", res.json().get("detail", "")).lower()

    async def test_10_upload_path_traversal_sanitized(self, client: AsyncClient, db_session):
        """Path traversal patterns in filename are neutralized and stored securely."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_doc10")
        club, secretary, _ = await _create_club_and_advisor(db_session, "Doc Club 10", admin)
        event_id = await _create_draft_event(client, club, secretary)

        files = {
            "file": ("../../../../etc/passwd.pdf", io.BytesIO(VALID_PDF_BYTES), "application/pdf")
        }
        res = await client.post(
            f"/api/v1/events/{event_id}/documents",
            files=files,
            headers=_auth_header(secretary),
        )
        assert res.status_code == 201
        doc_id = res.json()["id"]

        # Confirm stored_filename is a clean UUID
        doc = await db_session.scalar(select(Document).where(Document.id == uuid.UUID(doc_id)))
        assert ".." not in doc.stored_filename
        assert ".." not in doc.storage_path

    async def test_11_upload_rejected_in_submitted_status(self, client: AsyncClient, db_session):
        """Uploading while proposal is SUBMITTED is rejected (WorkflowStateError)."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_doc11")
        club, secretary, _ = await _create_club_and_advisor(db_session, "Doc Club 11", admin)
        hall = await _create_test_hall(db_session)

        # Create draft and submit
        event_id = await _create_draft_event(client, club, secretary)
        req_dt = datetime.now(UTC) + timedelta(days=20)
        s_time = req_dt.replace(hour=9, minute=0, second=0, microsecond=0)
        e_time = req_dt.replace(hour=18, minute=0, second=0, microsecond=0)
        await client.post(
            f"/api/v1/events/{event_id}/venue",
            json={
                "hall_id": str(hall.id),
                "requested_date": req_dt.date().isoformat(),
                "start_time": s_time.isoformat(),
                "end_time": e_time.isoformat(),
                "expected_audience": 150,
            },
            headers=_auth_header(secretary),
        )
        await client.post(
            f"/api/v1/events/{event_id}/budget",
            json={"expected_income": 5000.0, "institute_contribution": 10000.0},
            headers=_auth_header(secretary),
        )
        await client.post(
            f"/api/v1/events/{event_id}/budget/items",
            json={"category": "MATERIALS", "description": "Stationery", "estimated_amount": 5000.0},
            headers=_auth_header(secretary),
        )
        sub_res = await client.post(
            f"/api/v1/events/{event_id}/submit",
            json={"change_summary": "Ready for review"},
            headers=_auth_header(secretary),
        )
        assert sub_res.status_code == 200

        # Attempt upload in SUBMITTED status
        files = {"file": ("late_add.pdf", io.BytesIO(VALID_PDF_BYTES), "application/pdf")}
        res = await client.post(
            f"/api/v1/events/{event_id}/documents",
            files=files,
            headers=_auth_header(secretary),
        )
        assert res.status_code in (400, 403)

    async def test_12_upload_allowed_in_revision_required_status(
        self, client: AsyncClient, db_session
    ):
        """When proposal is in REVISION_REQUIRED, secretary may upload replacement documents."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_doc12")
        club, secretary, advisor = await _create_club_and_advisor(db_session, "Doc Club 12", admin)
        hall = await _create_test_hall(db_session)

        event_id = await _create_draft_event(client, club, secretary)
        req_dt = datetime.now(UTC) + timedelta(days=20)
        await client.post(
            f"/api/v1/events/{event_id}/venue",
            json={
                "hall_id": str(hall.id),
                "requested_date": req_dt.date().isoformat(),
                "start_time": req_dt.replace(hour=9, minute=0, second=0, microsecond=0).isoformat(),
                "end_time": req_dt.replace(hour=18, minute=0, second=0, microsecond=0).isoformat(),
                "expected_audience": 150,
            },
            headers=_auth_header(secretary),
        )
        await client.post(
            f"/api/v1/events/{event_id}/budget",
            json={"expected_income": 5000.0, "institute_contribution": 10000.0},
            headers=_auth_header(secretary),
        )
        await client.post(
            f"/api/v1/events/{event_id}/budget/items",
            json={"category": "MATERIALS", "description": "Stationery", "estimated_amount": 5000.0},
            headers=_auth_header(secretary),
        )
        await client.post(
            f"/api/v1/events/{event_id}/submit",
            json={"change_summary": "Ready"},
            headers=_auth_header(secretary),
        )

        # Advisor requests revision
        wf_res = await client.get(
            f"/api/v1/events/{event_id}/workflow", headers=_auth_header(secretary)
        )
        step1_id = next(s["id"] for s in wf_res.json()["steps"] if s["step_order"] == 1)
        await client.post(
            f"/api/v1/workflows/steps/{step1_id}/request-revision",
            json={"comments": "Please upload an updated brochure."},
            headers=_auth_header(advisor),
        )

        # Upload in REVISION_REQUIRED should succeed
        files = {"file": ("revised_brochure.pdf", io.BytesIO(VALID_PDF_BYTES), "application/pdf")}
        res = await client.post(
            f"/api/v1/events/{event_id}/documents",
            files=files,
            headers=_auth_header(secretary),
        )
        assert res.status_code == 201
        assert res.json()["original_filename"] == "revised_brochure.pdf"

    async def test_13_list_documents(self, client: AsyncClient, db_session):
        """GET /events/{id}/documents returns list of active documents."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_doc13")
        club, secretary, _ = await _create_club_and_advisor(db_session, "Doc Club 13", admin)
        event_id = await _create_draft_event(client, club, secretary)

        files1 = {"file": ("doc1.pdf", io.BytesIO(VALID_PDF_BYTES), "application/pdf")}
        files2 = {"file": ("doc2.png", io.BytesIO(VALID_PNG_BYTES), "image/png")}
        await client.post(
            f"/api/v1/events/{event_id}/documents", files=files1, headers=_auth_header(secretary)
        )
        await client.post(
            f"/api/v1/events/{event_id}/documents", files=files2, headers=_auth_header(secretary)
        )

        res = await client.get(
            f"/api/v1/events/{event_id}/documents", headers=_auth_header(secretary)
        )
        assert res.status_code == 200
        docs = res.json()
        assert len(docs) == 2

    async def test_14_download_document_by_secretary(self, client: AsyncClient, db_session):
        """Secretary who uploaded the document can download it successfully."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_doc14")
        club, secretary, _ = await _create_club_and_advisor(db_session, "Doc Club 14", admin)
        event_id = await _create_draft_event(client, club, secretary)

        files = {"file": ("download_test.pdf", io.BytesIO(VALID_PDF_BYTES), "application/pdf")}
        up_res = await client.post(
            f"/api/v1/events/{event_id}/documents", files=files, headers=_auth_header(secretary)
        )
        doc_id = up_res.json()["id"]

        dl_res = await client.get(
            f"/api/v1/events/{event_id}/documents/{doc_id}/download",
            headers=_auth_header(secretary),
        )
        assert dl_res.status_code == 200
        assert dl_res.content == VALID_PDF_BYTES

    async def test_15_download_document_by_reviewer(self, client: AsyncClient, db_session):
        """Institutional reviewer (e.g. Dean) can download attached event document."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_doc15")
        club, secretary, _ = await _create_club_and_advisor(db_session, "Doc Club 15", admin)
        dean = await _create_user(db_session, UserRole.DEAN_STUDENT_AFFAIRS, "dean_doc")
        event_id = await _create_draft_event(client, club, secretary)

        files = {"file": ("review_paper.pdf", io.BytesIO(VALID_PDF_BYTES), "application/pdf")}
        up_res = await client.post(
            f"/api/v1/events/{event_id}/documents", files=files, headers=_auth_header(secretary)
        )
        doc_id = up_res.json()["id"]

        dl_res = await client.get(
            f"/api/v1/events/{event_id}/documents/{doc_id}/download",
            headers=_auth_header(dean),
        )
        assert dl_res.status_code == 200
        assert dl_res.content == VALID_PDF_BYTES

    async def test_16_download_document_by_admin(self, client: AsyncClient, db_session):
        """SYSTEM_ADMIN can download attached document."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_doc16")
        club, secretary, _ = await _create_club_and_advisor(db_session, "Doc Club 16", admin)
        event_id = await _create_draft_event(client, club, secretary)

        files = {"file": ("admin_audit.pdf", io.BytesIO(VALID_PDF_BYTES), "application/pdf")}
        up_res = await client.post(
            f"/api/v1/events/{event_id}/documents", files=files, headers=_auth_header(secretary)
        )
        doc_id = up_res.json()["id"]

        dl_res = await client.get(
            f"/api/v1/events/{event_id}/documents/{doc_id}/download",
            headers=_auth_header(admin),
        )
        assert dl_res.status_code == 200

    async def test_17_cross_club_unauthorized_download_rejected(
        self, client: AsyncClient, db_session
    ):
        """Secretary of Club B is forbidden from downloading Club A's private documents."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_doc17")
        club_a, sec_a, _ = await _create_club_and_advisor(db_session, "Club Alpha", admin)
        club_b, sec_b, _ = await _create_club_and_advisor(db_session, "Club Beta", admin)
        event_id = await _create_draft_event(client, club_a, sec_a)

        files = {"file": ("confidential.pdf", io.BytesIO(VALID_PDF_BYTES), "application/pdf")}
        up_res = await client.post(
            f"/api/v1/events/{event_id}/documents", files=files, headers=_auth_header(sec_a)
        )
        doc_id = up_res.json()["id"]

        # Secretary B tries to download
        res = await client.get(
            f"/api/v1/events/{event_id}/documents/{doc_id}/download",
            headers=_auth_header(sec_b),
        )
        assert res.status_code == 403

    async def test_18_cross_club_unauthorized_listing_rejected(
        self, client: AsyncClient, db_session
    ):
        """Secretary of Club B cannot list Club A's documents."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_doc18")
        club_a, sec_a, _ = await _create_club_and_advisor(db_session, "Club Alpha2", admin)
        club_b, sec_b, _ = await _create_club_and_advisor(db_session, "Club Beta2", admin)
        event_id = await _create_draft_event(client, club_a, sec_a)

        res = await client.get(
            f"/api/v1/events/{event_id}/documents",
            headers=_auth_header(sec_b),
        )
        assert res.status_code == 403

    async def test_19_soft_delete_document(self, client: AsyncClient, db_session):
        """DELETE /events/{id}/documents/{doc_id} deactivates document (is_active=False)."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_doc19")
        club, secretary, _ = await _create_club_and_advisor(db_session, "Doc Club 19", admin)
        event_id = await _create_draft_event(client, club, secretary)

        files = {"file": ("to_delete.pdf", io.BytesIO(VALID_PDF_BYTES), "application/pdf")}
        up_res = await client.post(
            f"/api/v1/events/{event_id}/documents", files=files, headers=_auth_header(secretary)
        )
        doc_id = up_res.json()["id"]

        del_res = await client.delete(
            f"/api/v1/events/{event_id}/documents/{doc_id}",
            headers=_auth_header(secretary),
        )
        assert del_res.status_code == 200

        # Verify not present in listing
        list_res = await client.get(
            f"/api/v1/events/{event_id}/documents", headers=_auth_header(secretary)
        )
        assert not any(d["id"] == doc_id for d in list_res.json())

    async def test_20_download_deactivated_document_returns_404(
        self, client: AsyncClient, db_session
    ):
        """Attempting to download a deactivated document returns 404 Not Found."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_doc20")
        club, secretary, _ = await _create_club_and_advisor(db_session, "Doc Club 20", admin)
        event_id = await _create_draft_event(client, club, secretary)

        files = {"file": ("inactive.pdf", io.BytesIO(VALID_PDF_BYTES), "application/pdf")}
        up_res = await client.post(
            f"/api/v1/events/{event_id}/documents", files=files, headers=_auth_header(secretary)
        )
        doc_id = up_res.json()["id"]

        await client.delete(
            f"/api/v1/events/{event_id}/documents/{doc_id}", headers=_auth_header(secretary)
        )

        dl_res = await client.get(
            f"/api/v1/events/{event_id}/documents/{doc_id}/download",
            headers=_auth_header(secretary),
        )
        assert dl_res.status_code == 404

    async def test_21_delete_document_rejected_for_non_secretary(
        self, client: AsyncClient, db_session
    ):
        """Non-secretary member of another club cannot delete documents."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_doc21")
        club_a, sec_a, _ = await _create_club_and_advisor(db_session, "Club Alpha3", admin)
        club_b, sec_b, _ = await _create_club_and_advisor(db_session, "Club Beta3", admin)
        event_id = await _create_draft_event(client, club_a, sec_a)

        files = {"file": ("protected.pdf", io.BytesIO(VALID_PDF_BYTES), "application/pdf")}
        up_res = await client.post(
            f"/api/v1/events/{event_id}/documents", files=files, headers=_auth_header(sec_a)
        )
        doc_id = up_res.json()["id"]

        del_res = await client.delete(
            f"/api/v1/events/{event_id}/documents/{doc_id}",
            headers=_auth_header(sec_b),
        )
        assert del_res.status_code == 403

    async def test_22_audit_trail_recorded_for_document_lifecycle(
        self, client: AsyncClient, db_session
    ):
        """FILE_UPLOADED, FILE_DOWNLOADED, and FILE_DELETED audits are recorded."""
        admin = await _create_user(db_session, UserRole.SYSTEM_ADMIN, "admin_doc22")
        club, secretary, _ = await _create_club_and_advisor(db_session, "Doc Club 22", admin)
        event_id = await _create_draft_event(client, club, secretary)

        files = {"file": ("audit_doc.pdf", io.BytesIO(VALID_PDF_BYTES), "application/pdf")}
        up_res = await client.post(
            f"/api/v1/events/{event_id}/documents", files=files, headers=_auth_header(secretary)
        )
        doc_id = up_res.json()["id"]

        await client.get(
            f"/api/v1/events/{event_id}/documents/{doc_id}/download",
            headers=_auth_header(secretary),
        )
        await client.delete(
            f"/api/v1/events/{event_id}/documents/{doc_id}", headers=_auth_header(secretary)
        )

        # Inspect audit logs
        logs = list(
            (await db_session.scalars(select(AuditLog).where(AuditLog.entity_id == doc_id))).all()
        )
        actions = [log.action for log in logs]
        assert AuditAction.FILE_UPLOADED in actions
        assert AuditAction.FILE_DOWNLOADED in actions
        assert AuditAction.FILE_DELETED in actions

    async def test_23_unauthenticated_document_access_rejected(self, client: AsyncClient):
        """Unauthenticated requests to all document endpoints return 401."""
        fake_event = uuid.uuid4()
        fake_doc = uuid.uuid4()
        res1 = await client.get(f"/api/v1/events/{fake_event}/documents")
        assert res1.status_code == 401
        res2 = await client.get(f"/api/v1/events/{fake_event}/documents/{fake_doc}/download")
        assert res2.status_code == 401
        res3 = await client.delete(f"/api/v1/events/{fake_event}/documents/{fake_doc}")
        assert res3.status_code == 401
