"""POST /api/auth/login, POST /api/auth/logout, GET /api/auth/me (docs/specs/auth.md). The only routes under /api/auth.

Login answers 200 with {username, role} and sets the session cookie; a refusal is always the generic 401 "Invalid credentials" (wrong
password, unknown user, inactive user) or 429 "Too many failed sign-in attempts" with a Retry-After header. The token is rotated on every
login: a session cookie the request already carries is deleted before the new one is issued. Logout deletes the session and clears the
cookie (204). Both write their own audit rows (events login_ok / login_fail / login_blocked / lockout / logout)."""

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlmodel import Session

import core.auth as auth
from core.audit import write_audit
from core.config import settings

class LoginIn(BaseModel):
    username: str = Field(max_length=auth.MAX_USERNAME_LENGTH)
    password: str = Field(max_length=256)


class MeOut(BaseModel):
    username: str
    role: str


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _cookie_args() -> dict:
    return {"httponly": True, "samesite": "lax", "secure": settings.session_cookie_secure, "path": "/"}


def login(body: LoginIn, request: Request, response: Response) -> MeOut:
    ip, agent = client_ip(request), request.headers.get("user-agent")
    audit = {"method": "POST", "path": "/api/auth/login", "ip": ip}
    try:
        user = auth.authenticate(body.username, body.password, ip)
    except auth.LoginRejected as exc:
        write_audit(event=exc.event, status=exc.status, username=exc.username, **audit)
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        raise HTTPException(status_code=exc.status, detail=exc.detail, headers=headers) from None
    with Session(auth.engine) as session:
        auth.delete_session(session, auth.session_token(request))  # rotate: a cookie sent with the login does not survive it
        token, _row = auth.create_session(session, user, ip, agent)
    response.set_cookie(
        auth.COOKIE_NAME, token, max_age=int(auth.absolute_lifetime().total_seconds()), **_cookie_args()
    )
    write_audit(event="login_ok", status=200, user_id=user.id, username=user.username, **audit)
    return MeOut(username=user.username, role=user.role)


def logout(request: Request, response: Response, principal: Annotated[auth.Principal | None, Depends(auth.authorize)]) -> None:
    with Session(auth.engine) as session:
        auth.delete_session(session, auth.session_token(request))
    response.delete_cookie(auth.COOKIE_NAME, **_cookie_args())
    write_audit(
        event="logout", method="POST", path="/api/auth/logout", status=204, ip=client_ip(request),
        user_id=principal.user_id if principal else None, username=principal.username if principal else None,
    )


def me(principal: Annotated[auth.Principal | None, Depends(auth.authorize)]) -> MeOut:
    if principal is None:  # unreachable: the route is "viewer" in core/route_roles.py, so authorize answered 401
        raise HTTPException(status_code=401, detail="Not authenticated")
    return MeOut(username=principal.username, role=principal.role)


def register_auth_routes(app: FastAPI) -> None:
    """Adds the three routes straight onto `app` (not through include_router, so they are plain APIRoutes in `app.routes` like every
    other route and the route-role registry test sees them the same way)."""
    app.add_api_route("/api/auth/login", login, methods=["POST"], response_model=MeOut)
    app.add_api_route("/api/auth/logout", logout, methods=["POST"], status_code=204)
    app.add_api_route("/api/auth/me", me, methods=["GET"], response_model=MeOut)
