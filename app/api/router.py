from fastapi import APIRouter

from ..routes.activity_logs import router as activity_logs_router
from ..routes.admin import router as admin_router
from ..routes.auth import router as auth_router
from ..routes.student import router as student_router

api_router = APIRouter()
api_router.include_router(student_router, prefix="/api")
api_router.include_router(auth_router, prefix="/api")
api_router.include_router(admin_router, prefix="/api")
api_router.include_router(activity_logs_router, prefix="/api")
