from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qsl, urlencode, urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .ccavenue_crypto import decrypt, encrypt
from .config import settings
from .models.erp import ERPApplicationPayment, ERPHostelPayment

Payment = ERPApplicationPayment | ERPHostelPayment


class CCAvenueError(RuntimeError):
    pass


def require_configuration() -> None:
    required = {
        "CCAVENUE_MERCHANT_ID": settings.CCAVENUE_MERCHANT_ID,
        "CCAVENUE_ACCESS_CODE": settings.CCAVENUE_ACCESS_CODE,
        "CCAVENUE_WORKING_KEY": settings.CCAVENUE_WORKING_KEY,
        "CCAVENUE_GATEWAY_URL": settings.CCAVENUE_GATEWAY_URL,
        "CCAVENUE_REDIRECT_URL": settings.CCAVENUE_REDIRECT_URL,
        "CCAVENUE_CANCEL_URL": settings.CCAVENUE_CANCEL_URL,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise CCAvenueError(f"CCAvenue is not configured: {', '.join(missing)}.")


def new_order_id(prefix: str) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"MMC-{prefix}-{timestamp}-{secrets.token_hex(4).upper()}"


def serialize(parameters: dict[str, object]) -> str:
    return urlencode({key: str(value) for key, value in parameters.items() if value is not None})


def parse_response(enc_response: str) -> tuple[str, dict[str, str]]:
    plain_text = decrypt(enc_response, settings.CCAVENUE_WORKING_KEY or "")
    return plain_text, dict(parse_qsl(plain_text, keep_blank_values=True))


def create_gateway_payload(parameters: dict[str, object]) -> dict[str, str]:
    require_configuration()
    plain_text = serialize(parameters)
    return {
        "gateway_url": settings.CCAVENUE_GATEWAY_URL or "",
        "encRequest": encrypt(plain_text, settings.CCAVENUE_WORKING_KEY or ""),
        "access_code": settings.CCAVENUE_ACCESS_CODE or "",
    }


def find_payment(db: Session, order_id: str) -> Payment | None:
    payment = db.scalar(select(ERPApplicationPayment).where(ERPApplicationPayment.order_id == order_id))
    if payment:
        return payment
    return db.scalar(select(ERPHostelPayment).where(ERPHostelPayment.order_id == order_id))


def find_payment_by_id(db: Session, payment_id: int) -> Payment | None:
    application_payment = db.get(ERPApplicationPayment, payment_id)
    hostel_payment = db.get(ERPHostelPayment, payment_id)
    if application_payment and hostel_payment:
        raise CCAvenueError("Payment ID is ambiguous; use the payment history endpoint.")
    return application_payment or hostel_payment


def validate_response(payment: Payment, response: dict[str, str]) -> None:
    if response.get("merchant_id") != settings.CCAVENUE_MERCHANT_ID:
        raise CCAvenueError("CCAvenue merchant verification failed.")
    if response.get("order_id") != payment.order_id:
        raise CCAvenueError("CCAvenue order verification failed.")
    if response.get("currency", "").upper() != (payment.currency or "INR").upper():
        raise CCAvenueError("CCAvenue currency verification failed.")
    try:
        received = Decimal(response.get("amount", "")).quantize(Decimal("0.01"))
        expected = Decimal(payment.amount).quantize(Decimal("0.01"))
    except InvalidOperation as exc:
        raise CCAvenueError("CCAvenue returned an invalid amount.") from exc
    if not secrets.compare_digest(str(received), str(expected)):
        raise CCAvenueError("CCAvenue amount verification failed.")


def apply_response(payment: Payment, enc_response: str, plain_text: str, response: dict[str, str]) -> None:
    payment.encrypted_response = enc_response
    payment.decrypted_response = plain_text
    payment.tracking_id = response.get("tracking_id") or payment.tracking_id
    payment.bank_ref_no = response.get("bank_ref_no") or payment.bank_ref_no
    payment.payment_mode = response.get("payment_mode") or "CCAvenue"
    payment.payment_status = response.get("order_status") or "Invalid"
    payment.response_code = response.get("status_code") or response.get("response_code")
    payment.response_message = response.get("failure_message") or response.get("status_message")
    payment.transaction_id = payment.tracking_id or payment.order_id or payment.transaction_id
    payment.transaction_date = _parse_transaction_date(response.get("trans_date"))


def _parse_transaction_date(value: str | None) -> datetime:
    if value:
        for pattern in ("%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
            try:
                return datetime.strptime(value, pattern).replace(tzinfo=timezone.utc)
            except ValueError:
                pass
    return datetime.now(timezone.utc)


def merchant_api_url() -> str:
    host = urlparse(settings.CCAVENUE_GATEWAY_URL or "").hostname or ""
    if "test" in host.lower():
        return "https://apitest.ccavenue.com/apis/servlet/DoWebTrans"
    return "https://api.ccavenue.com/apis/servlet/DoWebTrans"


async def merchant_api(command: str, request_type: str = "JSON", **parameters: object) -> dict:
    require_configuration()
    request = {"reference_no": parameters.pop("reference_no", None), **parameters}
    encrypted = encrypt(serialize(request), settings.CCAVENUE_WORKING_KEY or "")
    payload = {
        "enc_request": encrypted,
        "access_code": settings.CCAVENUE_ACCESS_CODE,
        "command": command,
        "request_type": request_type,
        "response_type": "JSON",
        "version": "1.2",
    }
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(merchant_api_url(), data=payload)
        response.raise_for_status()
    data = dict(parse_qsl(response.text, keep_blank_values=True))
    enc_response = data.get("enc_response") or data.get("encResponse")
    if enc_response:
        decrypted = decrypt(enc_response, settings.CCAVENUE_WORKING_KEY or "")
        try:
            return json.loads(decrypted)
        except json.JSONDecodeError:
            return dict(parse_qsl(decrypted, keep_blank_values=True))
    try:
        return response.json()
    except ValueError as exc:
        raise CCAvenueError("CCAvenue Merchant API returned an invalid response.") from exc


async def order_status(order_id: str) -> dict:
    return await merchant_api("orderStatusTracker", order_no=order_id)


async def refund_order(reference_no: str, refund_amount: Decimal, refund_ref_no: str) -> dict:
    return await merchant_api(
        "refundOrder",
        reference_no=reference_no,
        refund_amount=f"{refund_amount:.2f}",
        refund_ref_no=refund_ref_no,
    )


async def cancel_order(reference_no: str) -> dict:
    return await merchant_api("cancelOrder", reference_no=reference_no)


async def confirm_order(reference_no: str, order_amount: Decimal) -> dict:
    return await merchant_api("confirmOrder", reference_no=reference_no, order_amount=f"{order_amount:.2f}")


async def lookup_order(order_id: str) -> dict:
    return await order_status(order_id)
