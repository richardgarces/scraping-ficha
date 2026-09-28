from __future__ import annotations

import os
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from retail.auth import COOKIE, SESSION_DAYS, read_session, safe_next, sign_session
from retail.search import connect_repo


def repo_or_503():
    repo = connect_repo()
    if repo is None:
        raise HTTPException(status_code=503, detail="MongoDB no está disponible.")
    return repo


def public_user(store, user_id: str | None) -> dict[str, Any] | None:
    if not user_id:
        return None
    found = store.find_user_by_id(user_id)
    return store._public_user(found) if found else None


def current_user(
    request: Request,
    store=None,
    *,
    required: bool = False,
    admin: bool = False,
    detail: str | None = None,
) -> dict[str, Any] | None:
    owns_store = store is None
    store = store or repo_or_503()
    try:
        user_id = read_session(request.cookies.get(COOKIE))
        user = public_user(store, user_id)
        if user and user.get("status") != "approved":
            user = None
        if required and not user:
            raise HTTPException(
                status_code=401,
                detail=detail or "Entra con tu cuenta para seguir productos.",
            )
        if admin:
            if not user:
                raise HTTPException(status_code=401, detail="Entra con tu cuenta de administrador.")
            if user.get("role") != "admin":
                raise HTTPException(status_code=403, detail="Solo el administrador puede hacer eso.")
        return user
    finally:
        if owns_store:
            store.close()


def request_is_admin(request: Request) -> bool:
    store = connect_repo()
    if store is None:
        return False
    try:
        user = current_user(request, store)
        return bool(user and user.get("role") == "admin")
    except HTTPException:
        return False
    finally:
        store.close()


def login_redirect(next_path: str) -> RedirectResponse:
    dest = safe_next(next_path, "/")
    return RedirectResponse(f"/entrar?next={quote(dest, safe='/')}", status_code=303)


def require_login_html(request: Request, *, next_path: str) -> RedirectResponse | None:
    """Cualquier cuenta aprobada. Sin sesión, vuelve a /entrar y luego a next_path."""
    store = connect_repo()
    if store is None:
        return login_redirect(next_path)
    try:
        if not current_user(request, store):
            return login_redirect(next_path)
        return None
    finally:
        store.close()


def require_admin_html(request: Request, *, next_path: str = "/ofertas") -> RedirectResponse | None:
    dest = safe_next(next_path, "/ofertas")
    login = f"/entrar?next={quote(dest, safe='/?=&')}"
    store = connect_repo()
    if store is None:
        return RedirectResponse(login, status_code=303)
    try:
        user = current_user(request, store)
        if not user or user.get("role") != "admin":
            return RedirectResponse(login, status_code=303)
        return None
    finally:
        store.close()


def set_session(response: Response, user_id: str) -> None:
    response.set_cookie(
        COOKIE,
        sign_session(user_id),
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=os.environ.get("RETAIL_COOKIE_SECURE", "0") in {"1", "true", "yes"},
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")
