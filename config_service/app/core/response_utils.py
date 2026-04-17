from config_service.app.core.response import APIResponse
from fastapi import HTTPException


def success_response(
    *,
    data=None,
    message: str = "Success"
) -> APIResponse:
    return APIResponse(
        success=True,
        message=message,
        data=data,
        errors=None
    )


def error_response(
    *,
    message: str,
    status_code: int = 400,
    errors=None
):
    """
    Use this instead of raising HTTPException directly
    """
    raise HTTPException(
        status_code=status_code,
        detail={
            "success": False,
            "message": message,
            "errors": errors,
            "data": None
        }
    )
