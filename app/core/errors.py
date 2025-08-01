from fastapi import HTTPException, status
from typing import Any, Dict, Optional

class VisionException(HTTPException):
    """Base exception for Vision Fintech API."""
    def __init__(
        self,
        status_code: int,
        detail: Any = None,
        headers: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)

class AuthenticationError(VisionException):
    """Authentication failed."""
    def __init__(self, detail: str = "Authentication failed"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            headers={"WWW-Authenticate": "Bearer"}
        )

class AuthorizationError(VisionException):
    """Authorization failed."""
    def __init__(self, detail: str = "Not enough permissions"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail
        )

class NotFoundError(VisionException):
    """Resource not found."""
    def __init__(self, detail: str = "Resource not found"):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=detail
        )

class ValidationError(VisionException):
    """Validation error."""
    def __init__(self, detail: str = "Validation failed"):
        super().__init__(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail
        )

class InsufficientFundsError(VisionException):
    """Insufficient wallet balance."""
    def __init__(self, detail: str = "Insufficient funds in wallet"):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail
        )

class PaymentFailedError(VisionException):
    """Payment processing failed."""
    def __init__(self, detail: str = "Payment processing failed"):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail
        )

class DuplicateTransactionError(VisionException):
    """Duplicate transaction detected."""
    def __init__(self, detail: str = "Duplicate transaction detected"):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail
        )

class ExternalServiceError(VisionException):
    """External service unavailable."""
    def __init__(self, detail: str = "External service temporarily unavailable"):
        super().__init__(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=detail
        )