from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..auth import authenticate_admin, create_access_token
from ..config import settings
from ..database import get_db
from ..dependencies import get_current_admin
from ..schemas import AdminLoginRequest, AdminLoginResponse, AdminMeResponse

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/login", response_model=AdminLoginResponse)
def admin_login(payload: AdminLoginRequest, db: Session = Depends(get_db)) -> AdminLoginResponse:
    admin = authenticate_admin(db, payload.username, payload.password)
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )

    expires = timedelta(minutes=settings.access_token_expire_minutes)
    token = create_access_token(subject=admin.username, expires_delta=expires)
    return AdminLoginResponse(
        access_token=token,
        expires_in_seconds=settings.access_token_expire_minutes * 60,
        username=admin.username,
    )


@router.get("/me", response_model=AdminMeResponse)
def admin_me(current_admin=Depends(get_current_admin)) -> AdminMeResponse:
    return AdminMeResponse(username=current_admin.username)

