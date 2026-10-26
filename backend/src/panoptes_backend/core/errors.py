class DomainError(Exception):
    code = "DOMAIN_ERROR"
    status_code = 400


class NotFoundError(DomainError):
    code = "NOT_FOUND"
    status_code = 404


class ConflictError(DomainError):
    code = "CONFLICT"
    status_code = 409
