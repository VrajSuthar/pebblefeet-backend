from typing import cast

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette import status
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppException
from app.core.settings import settings
from app.schema.response_schema import ErrorDetail, ResponseSchema, ResponseStatus


def _error_response(
    status_code: int, message: str, errors: list[ErrorDetail]
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=jsonable_encoder(
            ResponseSchema(
                status=ResponseStatus.ERROR,
                status_code=status_code,
                message=message,
                errors=errors,
            )
        ),
    )


async def app_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    exc = cast(AppException, exc)
    return _error_response(
        exc.status_code, exc.message, [ErrorDetail(code=exc.code, message=exc.message)]
    )


async def validation_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    # Same envelope as every other error, with one entry per invalid field,
    # e.g. field="variants.0.price" for a nested body field.
    exc = cast(RequestValidationError, exc)
    errors = [
        ErrorDetail(
            code="VALIDATION_ERROR",
            message=error["msg"].removeprefix("Value error, "),
            field=".".join(str(part) for part in error["loc"][1:]) or None,
        )
        for error in exc.errors()
    ]
    return _error_response(
        status.HTTP_422_UNPROCESSABLE_CONTENT, errors[0].message, errors
    )


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Framework errors such as 404 for an unknown route or 405 wrong method
    exc = cast(StarletteHTTPException, exc)
    message = str(exc.detail)
    return _error_response(
        exc.status_code, message, [ErrorDetail(code="HTTP_ERROR", message=message)]
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Traceback is logged by RequestLoggingMiddleware. Never send internal
    # details (SQL, file paths) to clients in production.
    detail = str(exc) if not settings.is_production else "Internal server error"
    return _error_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "Something went wrong. Please try again later.",
        [ErrorDetail(code="INTERNAL_SERVER_ERROR", message=detail)],
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
