from starlette import status


class AppException(Exception):
    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "BAD_REQUEST"

    def __init__(self, message: str, code: str | None = None):
        self.message = message
        if code:
            self.code = code
        super().__init__(message)


class BadRequestException(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "BAD_REQUEST"


class UnauthorizedException(AppException):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "UNAUTHORIZED"


class ConflictException(AppException):
    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"


class OtpExpiredException(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "OTP_EXPIRED"


class OtpInvalidException(AppException):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "OTP_INVALID"


class NotFoundException(AppException):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"


class ForbiddenException(AppException):
    status_code = status.HTTP_403_FORBIDDEN
    code = "FORBIDDEN"


class PaymentGatewayException(AppException):
    """Razorpay could not be reached or rejected the request."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "PAYMENT_GATEWAY_ERROR"


class ServiceUnavailableException(AppException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    code = "SERVICE_UNAVAILABLE"
