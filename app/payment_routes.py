from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .ccavenue_service import (
    CCAvenueError,
    apply_response,
    create_gateway_payload,
    find_payment,
    find_payment_by_id,
    new_order_id,
    parse_response,
    require_configuration,
    cancel_order,
    confirm_order,
    lookup_order,
    refund_order,
)
from .config import settings
from .database import get_db
from .dependencies import get_current_admin
from .models.erp import ERPApplication, ERPApplicationPayment, ERPHostelPayment, ERPStudent
from .services.payment_service import approve_application_payment, approve_hostel_payment

router = APIRouter(prefix="/payment", tags=["ccavenue-payment"])


class PaymentInitiateRequest(BaseModel):
    student_id: int = Field(gt=0)
    application_id: int = Field(gt=0)
    payment_type: str = Field(min_length=3, max_length=100)
    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)


class RefundRequest(BaseModel):
    reference_no: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0, max_digits=10, decimal_places=2)
    refund_reference: str = Field(min_length=1, max_length=100)


class MerchantReferenceRequest(BaseModel):
    reference_no: str = Field(min_length=1, max_length=100)
    amount: Decimal | None = Field(default=None, gt=0)


def _frontend_origin(request: Request) -> str:
    origin = request.headers.get("origin", "").rstrip("/")
    parsed = urlparse(origin)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return origin
    return ""


def _payment_kind(payment_type: str) -> str:
    normalized = payment_type.strip().lower()
    if "hostel" in normalized and "registration" not in normalized:
        return "hostel"
    if "registration" in normalized or "application" in normalized:
        return "application"
    raise HTTPException(status_code=422, detail="Unsupported payment type.")


def _redirect(origin: str, page: str, order_id: str) -> RedirectResponse | JSONResponse:
    if origin:
        return RedirectResponse(f"{origin}/student/{page}?{urlencode({'order_id': order_id})}", status_code=303)
    return JSONResponse({"order_id": order_id, "page": page})


def _receipt_number(payment: ERPApplicationPayment | ERPHostelPayment) -> str:
    prefix = "REG" if isinstance(payment, ERPApplicationPayment) else "HST"
    return f"MMC-{prefix}-{payment.id:08d}"


def _process_callback(db: Session, enc_response: str) -> tuple[ERPApplicationPayment | ERPHostelPayment, str]:
    require_configuration()
    plain_text, response = parse_response(enc_response)
    order_id = response.get("order_id", "")
    payment = find_payment(db, order_id)
    if not payment:
        raise CCAvenueError("CCAvenue order was not found.")

    from .ccavenue_service import validate_response

    validate_response(payment, response)
    incoming_status = response.get("order_status", "Invalid")
    if payment.status == "success":
        return payment, "payment-success.html"

    apply_response(payment, enc_response, plain_text, response)
    if incoming_status == "Success":
        payment.status = "success"
        if isinstance(payment, ERPApplicationPayment):
            approve_application_payment(student=payment.student, application=payment.application, payment=payment)
        else:
            approve_hostel_payment(student=payment.student, application=payment.application, payment=payment)
        payment.receipt_number = payment.receipt_number or _receipt_number(payment)
        page = "payment-success.html"
    elif incoming_status == "Aborted":
        payment.status = "cancelled"
        page = "payment-cancelled.html"
    else:
        payment.status = "failed"
        page = "payment-failed.html"
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment, page


@router.post("/initiate")
def initiate_payment(payload: PaymentInitiateRequest, request: Request, db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        require_configuration()
    except CCAvenueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    student = db.get(ERPStudent, payload.student_id)
    application = db.get(ERPApplication, payload.application_id)
    if not student or not student.is_active:
        raise HTTPException(status_code=404, detail="Student not found.")
    if not application or application.student_id != student.id:
        raise HTTPException(status_code=404, detail="Application not found for this student.")
    if application.form_status != "submitted":
        raise HTTPException(status_code=409, detail="Submit the hostel application before making payment.")

    kind = _payment_kind(payload.payment_type)
    if kind == "application":
        renewal = application.application_type.strip().lower() in {"existing", "renewal"}
        requested_renewal = "renewal" in payload.payment_type.strip().lower() or "existing" in payload.payment_type.strip().lower()
        if renewal != requested_renewal:
            expected_label = "Renewal Registration Fee" if renewal else "Registration Fee"
            raise HTTPException(status_code=422, detail=f"Payment type must be {expected_label} for this application.")
        expected_amount = Decimal(settings.RENEWAL_PAYMENT_AMOUNT if renewal else settings.APP_PAYMENT_AMOUNT)
        model = ERPApplicationPayment
        prefix = "REG"
    else:
        if not application.is_shortlisted or not application.allocated_hostel:
            raise HTTPException(status_code=409, detail="Shortlisting and hostel allocation are required before hostel fee payment.")
        expected_amount = Decimal(settings.hostel_fee(application.allocated_hostel))
        model = ERPHostelPayment
        prefix = "HST"
    if payload.amount.quantize(Decimal("0.01")) != expected_amount.quantize(Decimal("0.01")):
        raise HTTPException(status_code=422, detail="Payment amount does not match the fee configured by the college.")

    existing = db.scalar(
        select(model)
        .where(model.application_id == application.id, model.status.in_(("pending", "success")))
        .order_by(model.payment_date.desc())
    )
    if existing and existing.status == "success":
        raise HTTPException(status_code=409, detail="This fee is already paid.")
    if existing:
        raise HTTPException(status_code=409, detail=f"Payment order {existing.order_id} is already pending.")

    order_id = new_order_id(prefix)
    payment_values = dict(
        student_id=student.id,
        application_id=application.id,
        cycle_reference=application.active_cycle_reference,
        transaction_id=order_id,
        order_id=order_id,
        amount=expected_amount,
        payment_mode="CCAvenue",
        payment_status="Initiated",
        status="pending",
        currency="INR",
    )
    if kind == "hostel":
        payment_values["hostel_name"] = application.allocated_hostel
    payment = model(**payment_values)
    parameters = {
        "merchant_id": settings.CCAVENUE_MERCHANT_ID,
        "order_id": order_id,
        "currency": "INR",
        "amount": f"{expected_amount:.2f}",
        "redirect_url": settings.CCAVENUE_REDIRECT_URL,
        "cancel_url": settings.CCAVENUE_CANCEL_URL,
        "language": "EN",
        "billing_name": application.name or "Student",
        "billing_address": application.correspondence_address or "Magadh Mahila College",
        "billing_city": "Patna",
        "billing_state": "Bihar",
        "billing_zip": "800001",
        "billing_country": "India",
        "billing_tel": student.mobile_number,
        "billing_email": student.email,
        "merchant_param1": kind,
        "merchant_param2": _frontend_origin(request),
    }
    gateway = create_gateway_payload(parameters)
    payment.encrypted_request = gateway["encRequest"]
    db.add(payment)
    db.commit()
    return gateway


@router.post("/response")
def payment_response(encResp: str = Form(...), db: Session = Depends(get_db)):
    try:
        payment, page = _process_callback(db, encResp)
        _, response = parse_response(encResp)
        return _redirect(response.get("merchant_param2", ""), page, payment.order_id or "")
    except CCAvenueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/cancel")
def payment_cancel(encResp: str = Form(...), db: Session = Depends(get_db)):
    try:
        payment, page = _process_callback(db, encResp)
        _, response = parse_response(encResp)
        return _redirect(response.get("merchant_param2", ""), page, payment.order_id or "")
    except CCAvenueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/webhook")
def payment_webhook(encResp: str = Form(...), db: Session = Depends(get_db)) -> dict[str, str]:
    try:
        payment, _ = _process_callback(db, encResp)
        return {"status": "accepted", "order_id": payment.order_id or ""}
    except CCAvenueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/status/{order_id}")
def payment_status(order_id: str, db: Session = Depends(get_db)) -> dict:
    payment = find_payment(db, order_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Payment order not found.")
    return {
        "payment_id": payment.id,
        "order_id": payment.order_id,
        "status": payment.status,
        "payment_status": payment.payment_status,
        "amount": float(payment.amount),
        "currency": payment.currency,
        "tracking_id": payment.tracking_id,
        "payment_mode": payment.payment_mode,
        "receipt_number": payment.receipt_number,
        "receipt_url": f"/api/payment/receipt/{payment.id}?payment_type={'application' if isinstance(payment, ERPApplicationPayment) else 'hostel'}" if payment.receipt_path else None,
    }


@router.get("/history/{student_id}")
def payment_history(student_id: int, db: Session = Depends(get_db)) -> list[dict]:
    application = list(db.scalars(select(ERPApplicationPayment).where(ERPApplicationPayment.student_id == student_id)))
    hostel = list(db.scalars(select(ERPHostelPayment).where(ERPHostelPayment.student_id == student_id)))
    payments = [(item, "application") for item in application] + [(item, "hostel") for item in hostel]
    payments.sort(key=lambda item: item[0].payment_date, reverse=True)
    return [
        {
            "payment_id": payment.id,
            "payment_type": payment_type,
            "order_id": payment.order_id,
            "status": payment.status,
            "payment_status": payment.payment_status,
            "amount": float(payment.amount),
            "currency": payment.currency,
            "payment_date": payment.payment_date,
            "receipt_number": payment.receipt_number,
        }
        for payment, payment_type in payments
    ]


@router.get("/receipt/{payment_id}")
def payment_receipt(payment_id: int, payment_type: str = Query(..., pattern="^(application|hostel)$"), db: Session = Depends(get_db)):
    model = ERPApplicationPayment if payment_type == "application" else ERPHostelPayment
    payment = db.get(model, payment_id)
    if not payment or payment.status != "success" or not payment.receipt_path:
        raise HTTPException(status_code=404, detail="Verified payment receipt not found.")
    path = (Path(__file__).resolve().parents[1] / payment.receipt_path).resolve()
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Receipt file not found.")
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@router.get("/merchant/order/{order_id}")
async def merchant_order_lookup(order_id: str, _=Depends(get_current_admin)) -> dict:
    return await lookup_order(order_id)


@router.post("/merchant/refund")
async def merchant_refund(payload: RefundRequest, _=Depends(get_current_admin)) -> dict:
    return await refund_order(payload.reference_no, payload.amount, payload.refund_reference)


@router.post("/merchant/cancel")
async def merchant_cancel(payload: MerchantReferenceRequest, _=Depends(get_current_admin)) -> dict:
    return await cancel_order(payload.reference_no)


@router.post("/merchant/confirm")
async def merchant_confirm(payload: MerchantReferenceRequest, _=Depends(get_current_admin)) -> dict:
    if payload.amount is None:
        raise HTTPException(status_code=422, detail="Order amount is required for confirmation.")
    return await confirm_order(payload.reference_no, payload.amount)
