"""Domain errors.

Each error carries a stable machine-readable ``code``. The API layer maps them to
HTTP status codes (RFC 9457 problem details); workers map them to retry/fail.
"""


class DomainError(Exception):
    code: str = "domain_error"

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


# --- input validation
class EmptyFileError(DomainError):
    code = "empty_file"


class FileTooLargeError(DomainError):
    code = "file_too_large"


class UnsupportedFileTypeError(DomainError):
    code = "unsupported_file_type"


class TooManyPagesError(DomainError):
    code = "too_many_pages"


class UnreadableDocumentError(DomainError):
    code = "unreadable_document"


# --- state / lookup
class DocumentNotFoundError(DomainError):
    code = "document_not_found"


class IdempotencyKeyConflictError(DomainError):
    code = "idempotency_key_conflict"


class DuplicateIdempotencyKeyError(DomainError):
    """Raised by repositories when a concurrent insert won the race for the same key."""

    code = "duplicate_idempotency_key"


# --- infrastructure, as seen by the domain
class TransientError(DomainError):
    """A temporary failure (timeout, connection refused). Safe to retry."""

    code = "transient_error"


class PermanentError(DomainError):
    """Retrying will not help (corrupt input, invalid configuration)."""

    code = "permanent_error"
