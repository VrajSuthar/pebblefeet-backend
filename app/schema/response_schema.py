from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ResponseStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"


class ErrorDetail(BaseModel):
    code: str
    message: str
    field: str | None = None


class ResponseSchema(BaseModel, Generic[T]):
    status: ResponseStatus
    status_code: int
    message: str
    data: T | None = None
    errors: list[ErrorDetail] | None = None
