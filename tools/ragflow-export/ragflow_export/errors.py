"""Errors of the RAGFlow exporter. A Refused error means nothing was sent or written (exit 2)."""


class ExportError(Exception):
    exit_code = 1


class Refused(ExportError):
    exit_code = 2


class BadBaseUrl(Refused):
    pass


class InsecureTransport(Refused):
    pass


class ApiKeyError(Refused):
    pass


class OutDirRefused(Refused):
    pass


class FilterError(Refused):
    pass


class ReadOnlyViolation(ExportError):
    """A request other than a GET to a listing or download route. Raised before anything is sent."""


class UnsafeIdentifier(ExportError):
    """A dataset or document id that could escape its URL route or its folder."""


class RequestFailed(ExportError):
    pass


class RedirectRefused(RequestFailed):
    pass


class TransportError(RequestFailed):
    pass


class AuthError(RequestFailed):
    pass


class HttpError(RequestFailed):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class ApiError(RequestFailed):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


class ShapeError(RequestFailed):
    """A response that is not in the shape the tool expects. The tool stops rather than guess."""


class PaginationError(RequestFailed):
    pass


class IncompleteExport(ExportError):
    def __init__(self, message: str, failures: list[dict]):
        super().__init__(message)
        self.failures = failures
