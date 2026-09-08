from __future__ import annotations

import hashlib
import secrets
from datetime import date, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..erp_dependencies import get_current_student
from ..erp_models import ActivityLog, ERPApplication, ERPApplicationPayment, ERPComplaint, ERPHostelPayment, ERPStudent
from ..erp_security import create_access_token, generate_random_password, hash_password, validate_password_strength, verify_password
from ..erp_schemas import (
    ApplicationFormPayload,
    ComplaintCreateRequest,
    ComplaintListResponse,
    ComplaintResponse,
    GenericMessageResponse,
    StudentDashboardResponse,
    StudentCompletePasswordResetRequest,
    StudentForgotPasswordRequest,
    StudentLoginRequest,
    StudentLoginResponse,
    StudentPasswordResetRequest,
    StudentRegistrationRequest,
    StudentRegistrationResponse,
)
from ..services.email_service import send_account_email
from ..services.application_number import generate_application_number
from ..services.erp_service import (
    APPLICATION_FIELDS,
    REQUIRED_SUBMISSION_FIELDS,
    application_summary,
    build_asset_url,
    build_student_dashboard,
    calculate_percentage,
    can_edit_application,
    clean_text,
    current_cycle_reference,
    ensure_valid_hostel_name,
    latest_application_payment,
    latest_hostel_payment,
    next_renewal_cycle_reference,
    parse_optional_date,
    parse_optional_decimal,
    utc_now,
)
from ..utils.file_storage import save_upload_file

router = APIRouter(tags=["erp-student"])

_forgot_password_attempts: dict[str, list[float]] = {}


class HostelPreferenceRequest(BaseModel):
    hostel_name: str


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _normalize_login_identifier(value: str) -> str:
    return value.strip()


def _normalize_mobile_number(value: str) -> str:
    return "".join(char for char in value if char.isdigit()) or value.strip()


def _normalize_aadhaar_number(value: str | None) -> str:
    if not value:
        return ""
    return "".join(char for char in value if char.isdigit()) or value.strip()


def _hash_reset_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _log_password_reset_event(
    db: Session,
    *,
    student_id: int | None,
    action: str,
    old_values: dict[str, object | None] | None = None,
    new_values: dict[str, object | None] | None = None,
) -> None:
    db.add(
        ActivityLog(
            entity_type="student",
            entity_id=str(student_id or "unknown"),
            action=action,
            old_values=json_dumps(old_values or {}),
            new_values=json_dumps(new_values or {}),
        )
    )


def json_dumps(value: dict[str, object | None]) -> str:
    import json

    return json.dumps(value, default=str)


def _enforce_forgot_password_rate_limit(request: Request, email: str) -> None:
    import time

    now = time.time()
    client = request.client.host if request.client else "anonymous"
    key = f"{client}:{email}"
    attempts = [timestamp for timestamp in _forgot_password_attempts.get(key, []) if now - timestamp < 900]
    if len(attempts) >= 5:
        _forgot_password_attempts[key] = attempts
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many reset attempts. Please try again later.")
    attempts.append(now)
    _forgot_password_attempts[key] = attempts


def _find_student_by_identifier(db: Session, identifier: str) -> ERPStudent | None:
    normalized_identifier = _normalize_login_identifier(identifier)
    if "@" in normalized_identifier:
        return db.scalar(select(ERPStudent).where(ERPStudent.email == _normalize_email(normalized_identifier)))
    normalized_mobile = _normalize_mobile_number(normalized_identifier)
    if normalized_mobile.isdigit() and len(normalized_mobile) >= 10:
        student = db.scalar(select(ERPStudent).where(ERPStudent.mobile_number == normalized_mobile))
        if student:
            return student
    return db.scalar(select(ERPStudent).where(ERPStudent.application_number == normalized_identifier))


def _existing_student_by_email_or_mobile(db: Session, email: str, mobile_number: str) -> ERPStudent | None:
    return db.scalar(
        select(ERPStudent).where(
            (ERPStudent.email == email) | (ERPStudent.mobile_number == mobile_number)
        )
    )


async def _parse_application_form(request: Request) -> tuple[dict[str, object | None], dict[str, object | None]]:
    form = await request.form()
    files = {
        "student_photo": form.get("student_photo") or form.get("student_image") or form.get("photo"),
        "aadhaar_card": form.get("aadhaar_card"),
        "college_id": form.get("college_id"),
        "marksheet": form.get("marksheet"),
    }

    aliases = {
        "aadhaar_number": ["aadhaar_number", "aadhar_number"],
        "guardian_mobile_number": ["guardian_mobile_number", "local_guardian_mobile", "guardian_mobile"],
        "intermediate_board": ["intermediate_board", "intermediate_board_name"],
        "total_marks": ["total_marks", "intermediate_total_marks"],
        "marks_obtained": ["marks_obtained", "intermediate_marks_obtained"],
        "result_type": ["result_type", "intermediate_result_type"],
        "aggregate_percentage": ["aggregate_percentage", "intermediate_percentage"],
        "roll_number": ["roll_number", "roll_no"],
        "preferred_hostel": ["preferred_hostel", "hostel_name", "hostel_type"],
    }

    data: dict[str, object | None] = {}
    for field_name in APPLICATION_FIELDS:
        possible_keys = aliases.get(field_name, [field_name])
        raw_value = None
        for key in possible_keys:
            if key in form:
                raw_value = form.get(key)
                break
        data[field_name] = raw_value

    data["date_of_birth"] = parse_optional_date(data.get("date_of_birth"))
    data["total_marks"] = parse_optional_decimal(data.get("total_marks"))
    data["marks_obtained"] = parse_optional_decimal(data.get("marks_obtained"))
    data["aggregate_percentage"] = parse_optional_decimal(data.get("aggregate_percentage"))
    if data["aggregate_percentage"] is None:
        data["aggregate_percentage"] = calculate_percentage(
            data.get("total_marks"),
            data.get("marks_obtained"),
        )

    for key, value in list(data.items()):
        if key in {"date_of_birth", "total_marks", "marks_obtained", "aggregate_percentage"}:
            continue
        data[key] = clean_text(value)

    if data.get("preferred_hostel"):
        data["preferred_hostel"] = ensure_valid_hostel_name(str(data["preferred_hostel"]))

    return data, files


def _get_or_create_application(student: ERPStudent, db: Session) -> ERPApplication:
    application = student.application
    if application:
        if not application.active_cycle_reference:
            application.active_cycle_reference = current_cycle_reference(student, application)
        if not application.application_type:
            application.application_type = "new"
        return application

    application = ERPApplication(
        student_id=student.id,
        email=student.email,
        mobile_number=student.mobile_number,
        date_of_birth=student.date_of_birth,
        college_name="Magadh Mahila College",
        application_type="new",
        active_cycle_reference=current_cycle_reference(student, None),
    )
    db.add(application)
    db.flush()
    return application


def _apply_application_payload(
    *,
    student: ERPStudent,
    application: ERPApplication,
    payload: dict[str, object | None],
    files: dict[str, object | None],
) -> None:
    application.email = student.email
    application.mobile_number = student.mobile_number

    for field_name, value in payload.items():
        if field_name in {"email", "mobile_number"}:
            continue
        if field_name == "preferred_hostel" and value is None:
            continue
        setattr(application, field_name, value)

    if application.date_of_birth is None:
        application.date_of_birth = student.date_of_birth

    photo = files.get("student_photo")
    if photo and getattr(photo, "filename", None):
        application.student_photo_path = save_upload_file(
            photo,
            settings.photo_dir,
            prefix=f"student_{student.id}",
        )

    for field_name, file_obj, prefix in (
        ("aadhaar_card_path", files.get("aadhaar_card"), "aadhaar"),
        ("college_id_path", files.get("college_id"), "college_id"),
        ("marksheet_path", files.get("marksheet"), "marksheet"),
    ):
        if file_obj and getattr(file_obj, "filename", None):
            setattr(
                application,
                field_name,
                save_upload_file(file_obj, settings.photo_dir, prefix=f"{prefix}_{student.id}"),
            )


def _validate_submission(application: ERPApplication) -> list[str]:
    missing_fields: list[str] = []
    for field_name in REQUIRED_SUBMISSION_FIELDS:
        value = getattr(application, field_name)
        if value is None or str(value).strip() == "":
            missing_fields.append(field_name)

    for field_name in ("student_photo_path", "aadhaar_card_path", "college_id_path", "marksheet_path"):
        if not getattr(application, field_name):
            missing_fields.append(field_name.replace("_path", ""))

    return missing_fields


def _reset_for_new_cycle(student: ERPStudent, application: ERPApplication) -> None:
    application.application_type = "renewal"
    application.previous_application_number = student.application_number
    application.active_cycle_reference = next_renewal_cycle_reference(student, application)
    application.renewal_reference_number = application.active_cycle_reference.replace("APP-", "REN-", 1)
    application.form_status = "draft"
    application.is_verified = False
    application.is_shortlisted = False
    application.preferred_hostel = None
    application.allocated_hostel = None
    application.allocated_room_id = None
    application.bed_number = None
    application.submitted_at = None
    application.verified_at = None
    application.shortlisted_at = None
    application.hostel_allocated_at = None


@router.post("/register", response_model=StudentRegistrationResponse, status_code=status.HTTP_201_CREATED)
def register_student(payload: StudentRegistrationRequest, db: Session = Depends(get_db)) -> StudentRegistrationResponse:
    email = _normalize_email(payload.email)
    mobile_number = _normalize_mobile_number(payload.mobile_number)
    if _existing_student_by_email_or_mobile(db, email, mobile_number):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Student with this email or mobile number already exists.",
        )

    generated_password = clean_text(payload.password) or generate_random_password()
    student = ERPStudent(
        application_number=f"TEMP-{uuid4().hex[:10]}",
        email=email,
        date_of_birth=payload.date_of_birth,
        mobile_number=mobile_number,
        password_hash=hash_password(generated_password),
    )
    db.add(student)
    db.flush()
    student.application_number = generate_application_number(student.id)
    db.commit()
    db.refresh(student)

    return StudentRegistrationResponse(
        application_number=student.application_number,
        email=student.email,
        mobile_number=student.mobile_number,
        password=generated_password,
        message="Registration completed successfully.",
    )


@router.post("/login", response_model=StudentLoginResponse)
def login_student(payload: StudentLoginRequest, db: Session = Depends(get_db)) -> StudentLoginResponse:
    login_identifier = _normalize_login_identifier(payload.email)
    student = _find_student_by_identifier(db, login_identifier)

    if not student or not student.is_active or not verify_password(payload.password, student.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password.")

    verification_dob = payload.date_of_birth or payload.dob
    if verification_dob and verification_dob != student.date_of_birth:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Date of birth does not match.")

    token = create_access_token(subject=str(student.id), role="student")
    application_completed = bool(student.application and student.application.form_status == "submitted")

    return StudentLoginResponse(
        access_token=token,
        application_completed=application_completed,
        redirect="/dashboard" if application_completed else "/application-form",
        application_number=student.application_number,
        student_id=student.id,
        student_name=student.application.name if student.application else None,
        force_password_change=student.force_password_change,
    )


@router.post("/forgot-password", response_model=GenericMessageResponse)
def request_student_password_reset(
    payload: StudentForgotPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
) -> GenericMessageResponse:
    email = _normalize_email(payload.email)
    aadhaar_number = _normalize_aadhaar_number(payload.aadhaar_number)
    _enforce_forgot_password_rate_limit(request, email)

    student = db.scalar(select(ERPStudent).where(ERPStudent.email == email, ERPStudent.is_active.is_(True)))
    stored_aadhaar = _normalize_aadhaar_number(student.application.aadhaar_number) if student and student.application else None
    if not student or stored_aadhaar != aadhaar_number:
        _log_password_reset_event(
            db,
            student_id=None,
            action="password_reset_request_failed",
            new_values={"email": email, "reason": "invalid_email_or_aadhaar"},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Email or Aadhaar Number")

    now = utc_now()
    if student.reset_last_attempt_at:
        last_attempt = student.reset_last_attempt_at
        if last_attempt.tzinfo is None:
            last_attempt = last_attempt.replace(tzinfo=timezone.utc)
        if student.reset_attempt_count >= 5 and now - last_attempt < timedelta(minutes=15):
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many reset attempts. Please try again later.")

    raw_token = secrets.token_urlsafe(32)
    student.reset_token_hash = _hash_reset_token(raw_token)
    student.reset_token_expires_at = now + timedelta(minutes=settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES)
    student.reset_requested_at = now
    student.reset_last_attempt_at = now
    student.reset_attempt_count = (student.reset_attempt_count or 0) + 1
    db.add(student)
    _log_password_reset_event(
        db,
        student_id=student.id,
        action="password_reset_requested",
        new_values={"email": email, "expires_at": student.reset_token_expires_at},
    )
    email_status = send_account_email(
        recipient=student.email,
        subject="Student password reset link",
        body=f"Use this reset token within {settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes: {raw_token}",
    )
    db.commit()
    return GenericMessageResponse(
        message="Password Reset Email Sent" if email_status != "skipped" else f"Password reset token: {raw_token}"
    )


@router.post("/complete-password-reset", response_model=GenericMessageResponse)
def complete_student_password_reset(
    payload: StudentCompletePasswordResetRequest,
    db: Session = Depends(get_db),
) -> GenericMessageResponse:
    password_error = validate_password_strength(payload.new_password, payload.confirm_password)
    if password_error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=password_error)

    token_hash = _hash_reset_token(payload.token)
    student = db.scalar(select(ERPStudent).where(ERPStudent.reset_token_hash == token_hash))
    now = utc_now()
    if not student or not student.reset_token_expires_at:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired password reset link.")
    expires_at = student.reset_token_expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        student.reset_token_hash = None
        student.reset_token_expires_at = None
        db.add(student)
        _log_password_reset_event(db, student_id=student.id, action="password_reset_expired")
        db.commit()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password reset link has expired.")

    student.password_hash = hash_password(payload.new_password)
    student.force_password_change = False
    student.reset_token_hash = None
    student.reset_token_expires_at = None
    student.reset_attempt_count = 0
    student.reset_last_attempt_at = None
    db.add(student)
    _log_password_reset_event(db, student_id=student.id, action="password_reset_completed")
    db.commit()
    return GenericMessageResponse(message="Password Changed Successfully")


@router.post("/reset-password", response_model=GenericMessageResponse)
def reset_student_password(
    payload: StudentPasswordResetRequest,
    db: Session = Depends(get_db),
) -> GenericMessageResponse:
    student = _find_student_by_identifier(db, payload.identifier)
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student record not found.")

    normalized_mobile_number = _normalize_mobile_number(payload.mobile_number)
    if student.date_of_birth != payload.date_of_birth or _normalize_mobile_number(student.mobile_number) != normalized_mobile_number:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Student verification details do not match.",
        )

    password_error = validate_password_strength(payload.new_password)
    if password_error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=password_error)

    student.password_hash = hash_password(payload.new_password)
    student.force_password_change = False
    db.add(student)
    db.commit()
    return GenericMessageResponse(message="Password reset completed successfully.")


@router.get("/application", response_model=ApplicationFormPayload)
def get_application_form(
    student: ERPStudent = Depends(get_current_student),
) -> ApplicationFormPayload:
    application = student.application
    summary = application_summary(student, application)
    summary["student_photo_url"] = build_asset_url(application.student_photo_path) if application else None

    return ApplicationFormPayload(
        application_number=student.application_number,
        application_type=application.application_type if application else "new",
        cycle_reference=application.active_cycle_reference if application else current_cycle_reference(student, application),
        renewal_reference_number=application.renewal_reference_number if application else None,
        previous_application_number=application.previous_application_number if application else None,
        email=student.email,
        mobile_number=student.mobile_number,
        registration_date_of_birth=student.date_of_birth,
        form_status=application.form_status if application else "not_started",
        is_editable=can_edit_application(application),
        data=summary,
    )


@router.post("/application/start-renewal", response_model=GenericMessageResponse)
def start_hostel_renewal(
    db: Session = Depends(get_db),
    student: ERPStudent = Depends(get_current_student),
) -> GenericMessageResponse:
    application = _get_or_create_application(student, db)
    _reset_for_new_cycle(student, application)
    db.add(application)
    db.commit()
    return GenericMessageResponse(message="Hostel renewal started. Existing data has been loaded into the same application form.")


@router.post("/application/draft", response_model=GenericMessageResponse)
async def save_application_draft(
    request: Request,
    db: Session = Depends(get_db),
    student: ERPStudent = Depends(get_current_student),
) -> GenericMessageResponse:
    application = _get_or_create_application(student, db)

    payload, files = await _parse_application_form(request)
    _apply_application_payload(student=student, application=application, payload=payload, files=files)
    if application.form_status != "submitted":
        application.form_status = "draft"
    db.add(application)
    db.commit()
    return GenericMessageResponse(message="Draft saved successfully.")


@router.post("/application/submit", response_model=GenericMessageResponse)
async def submit_application(
    request: Request,
    db: Session = Depends(get_db),
    student: ERPStudent = Depends(get_current_student),
) -> GenericMessageResponse:
    application = _get_or_create_application(student, db)

    payload, files = await _parse_application_form(request)
    _apply_application_payload(student=student, application=application, payload=payload, files=files)

    missing_fields = _validate_submission(application)
    if missing_fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Missing required fields: {', '.join(missing_fields)}.",
        )

    application.form_status = "submitted"
    application.submitted_at = utc_now()
    db.add(application)
    db.commit()
    return GenericMessageResponse(message="Application submitted successfully.")


@router.post("/hostel/preference", response_model=GenericMessageResponse)
def save_hostel_preference(
    payload: HostelPreferenceRequest,
    db: Session = Depends(get_db),
    student: ERPStudent = Depends(get_current_student),
) -> GenericMessageResponse:
    application = student.application
    if not application or not application.is_shortlisted:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Shortlist status is pending.")
    if latest_hostel_payment(application):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Hostel payment is already completed.")
    if application.allocated_hostel:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Hostel has already been allocated.")

    application.preferred_hostel = ensure_valid_hostel_name(payload.hostel_name)
    db.add(application)
    db.commit()
    return GenericMessageResponse(message="Hostel preference saved successfully.")


@router.get("/dashboard", response_model=StudentDashboardResponse)
def get_dashboard(student: ERPStudent = Depends(get_current_student)) -> StudentDashboardResponse:
    return StudentDashboardResponse(**build_student_dashboard(student))


@router.get("/complaints", response_model=ComplaintListResponse)
def list_student_complaints(
    db: Session = Depends(get_db),
    student: ERPStudent = Depends(get_current_student),
) -> ComplaintListResponse:
    items = list(
        db.scalars(
            select(ERPComplaint)
            .where(ERPComplaint.student_id == student.id)
            .order_by(ERPComplaint.created_at.desc())
        )
    )
    return ComplaintListResponse(total=len(items), items=[ComplaintResponse.model_validate(item) for item in items])


@router.post("/complaints", response_model=ComplaintResponse, status_code=status.HTTP_201_CREATED)
def create_student_complaint(
    payload: ComplaintCreateRequest,
    db: Session = Depends(get_db),
    student: ERPStudent = Depends(get_current_student),
) -> ComplaintResponse:
    next_id = (db.scalar(select(func.count(ERPComplaint.id))) or 0) + 1
    complaint = ERPComplaint(
        student_id=student.id,
        application_id=student.application.id if student.application else None,
        ticket_number=f"MMC-CMP-{next_id:05d}",
        subject=clean_text(payload.subject) or "Complaint",
        category=clean_text(payload.category) or "General",
        description=clean_text(payload.description) or "",
    )
    db.add(complaint)
    db.commit()
    db.refresh(complaint)
    return ComplaintResponse.model_validate(complaint)
