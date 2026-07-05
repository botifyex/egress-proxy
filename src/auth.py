from fastapi import HTTPException, Request, status

from src.config import settings


class Unauthorized(HTTPException):
    def __init__(self) -> None:
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized"
        )


def verify_key(request: Request) -> None:
    key = request.headers.get(settings.proxy.header)
    if key != settings.proxy.key:
        raise Unauthorized()
