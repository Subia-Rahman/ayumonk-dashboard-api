from fastapi import APIRouter
from .auth import router as auth_router
from .access_control import router as access_control_router
from .rbac_matrix import router as rbac_matrix_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(access_control_router)
router.include_router(rbac_matrix_router)
