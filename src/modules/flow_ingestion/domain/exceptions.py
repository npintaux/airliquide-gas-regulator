"""Exceptions taxonomy for flow ingestion subsystem."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class FlowIngestionError(Exception):
    """Base exception for all flow ingestion domain errors.

    Attributes:
        message: Human-readable error description.
        code: Machine-readable error category string.
        status_code: Suggested HTTP status code.
        details: Optional structured violation metadata.
    """

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_INGESTION_ERROR",
        status_code: int = 500,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        """Initializes FlowIngestionError with diagnostic fields."""
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = dict(details) if details is not None else {}


class MalformedPayloadError(FlowIngestionError):
    """Raised when request payload is syntactically invalid or missing fields."""

    def __init__(
        self,
        message: str,
        code: str = "MALFORMED_PAYLOAD",
        status_code: int = 400,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        """Initializes MalformedPayloadError with 400 Bad Request default."""
        super().__init__(message, code=code, status_code=status_code, details=details)


class SignatureVerificationError(FlowIngestionError):
    """Raised when HMAC signature fails or key is missing/invalid."""

    def __init__(
        self,
        message: str,
        code: str = "INVALID_SIGNATURE",
        status_code: int = 401,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        """Initializes SignatureVerificationError with 401 Unauthorized default."""
        super().__init__(message, code=code, status_code=status_code, details=details)


class SequenceDiscontinuityError(FlowIngestionError):
    """Raised when frame sequence number violates monotonic order."""

    def __init__(
        self,
        message: str,
        code: str = "SEQUENCE_DISCONTINUITY",
        status_code: int = 422,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        """Initializes SequenceDiscontinuityError with 422 Unprocessable default."""
        super().__init__(message, code=code, status_code=status_code, details=details)


class JitterThresholdExceededError(FlowIngestionError):
    """Raised when packet arrival interval exceeds allowed jitter tolerance."""

    def __init__(
        self,
        message: str,
        code: str = "JITTER_THRESHOLD_EXCEEDED",
        status_code: int = 422,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        """Initializes JitterThresholdExceededError with 422 Unprocessable default."""
        super().__init__(message, code=code, status_code=status_code, details=details)


class RateLimitExceededError(FlowIngestionError):
    """Raised when stream ingestion exceeds rate/burst thresholds."""

    def __init__(
        self,
        message: str,
        code: str = "RATE_LIMIT_EXCEEDED",
        status_code: int = 422,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        """Initializes RateLimitExceededError with 422 Unprocessable default."""
        super().__init__(message, code=code, status_code=status_code, details=details)


class PublisherUnavailableError(FlowIngestionError):
    """Raised when downstream message broker is unreachable or fails."""

    def __init__(
        self,
        message: str,
        code: str = "PUBLISHER_UNAVAILABLE",
        status_code: int = 500,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        """Initializes PublisherUnavailableError with 500 Server Error default."""
        super().__init__(message, code=code, status_code=status_code, details=details)


class InternalIngestionError(FlowIngestionError):
    """Raised when an unhandled internal error occurs."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_INGESTION_ERROR",
        status_code: int = 500,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        """Initializes InternalIngestionError with 500 Server Error default."""
        super().__init__(message, code=code, status_code=status_code, details=details)
