from starlette import status

from app.schema.response_schema import ResponseSchema, ResponseStatus


def ok(message: str, data=None, status_code: int = status.HTTP_200_OK) -> ResponseSchema:
    return ResponseSchema(
        status=ResponseStatus.SUCCESS,
        status_code=status_code,
        message=message,
        data=data,
    )


def created(message: str, data=None) -> ResponseSchema:
    return ok(message, data, status_code=status.HTTP_201_CREATED)
