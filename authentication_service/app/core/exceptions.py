from __future__ import annotations
from logging import getLogger
from config_service.app.core.business_exceptions import BusinessException
from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse



logger = getLogger(__name__)

async def http_exception_handler(request: Request, exc: HTTPException):
    """
    Handles error_response() and any HTTPException
    """
    logger.warning(
        "HTTPException | %s %s | %s",
        request.method,
        request.url,
        exc.detail
    )
    if isinstance(exc.detail, dict):
        return JSONResponse(
            status_code=exc.status_code,
            content=exc.detail
        )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "message": exc.detail,
            "errors": None,
            "data": None
        }
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """
    Handles Pydantic validation errors
    """
    logger.warning(
        "ValidationError | %s %s | %s",
        request.method,
        request.url,
        exc.errors()
    )
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "message": "Validation error",
            "errors": exc.errors(),
            "data": None
        }
    )


async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception(
        "UnhandledException | %s %s",
        request.method,
        request.url
    )

    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "message": "Internal server error",
            "data": None,
            "errors": None
        }
    )

async def business_exception_handler(request: Request, exc: BusinessException):
    logger.warning(
        "BusinessException | %s %s | %s",
        request.method,
        request.url,
        exc.message
    )
    
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "message": exc.message,
            "data": None,
            "errors": exc.errors
        }
    )