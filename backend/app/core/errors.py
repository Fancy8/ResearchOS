class DomainError(Exception):
    def __init__(self, code: str, message: str, status: int = 400, details=None):
        self.code, self.message, self.status, self.details = code, message, status, details


def missing():
    raise DomainError("RESOURCE_NOT_FOUND", "资料不存在或不可访问", 404)


def conflict(current_version):
    raise DomainError(
        "VERSION_CONFLICT", "资料已被修改，请查看最新版本后重试", 409, {"current_version": current_version}
    )
