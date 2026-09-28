from __future__ import annotations

from datetime import datetime, timezone
from datetime import timedelta
import hashlib
import secrets
from typing import Any

from retail.auth import admin_email, admin_password, hash_password, normalize_email, valid_email, valid_login, verify_password


def _now() -> datetime:
    return datetime.now(timezone.utc)


CONFIRMATION_HOURS = 24
PASSWORD_RESET_MINUTES = 30


def signup(store, email: str, password: str, name: str = "") -> dict[str, Any]:
    """Crea una cuenta pendiente y entrega una vez el token de confirmación."""
    clean = normalize_email(email)
    if not valid_email(clean):
        raise ValueError("Escribe un email válido.")
    if len(password or "") < 8:
        raise ValueError("La clave debe tener al menos 8 caracteres.")
    existing = store.find_user_by_email(clean)
    if existing and existing.get("status") == "approved" and existing.get("password_hash"):
        raise ValueError("Ese email ya tiene cuenta. Entra con tu clave.")
    if existing and existing.get("status") == "rejected":
        raise ValueError("El administrador no aceptó ese email.")

    is_admin = clean == admin_email()
    status = "approved" if is_admin else "pending"
    role = "admin" if is_admin or (existing and existing.get("role") == "admin") else "user"
    token = secrets.token_urlsafe(32) if status == "pending" else ""
    document = {
        "email": clean,
        "name": (name or "").strip(),
        "password_hash": hash_password(password),
        "role": role,
        "status": status,
        "approved_at": _now() if status == "approved" else None,
        "confirmation_token_hash": hashlib.sha256(token.encode()).hexdigest() if token else None,
        "confirmation_expires_at": _now() + timedelta(hours=CONFIRMATION_HOURS) if token else None,
    }
    if existing:
        updated = store.update_user(str(existing.get("_id") or existing.get("id")), document)
        public = store._public_user(updated or existing)
        if public is not None and token:
            public["_confirmation_token"] = token
        return public
    created = store.insert_user(document)
    public = store._public_user(created)
    if public is not None and token:
        public["_confirmation_token"] = token
    return public


def confirm_email(store, token: str) -> dict[str, Any]:
    clean = str(token or "").strip()
    if not clean:
        raise ValueError("El enlace de confirmación no es válido.")
    digest = hashlib.sha256(clean.encode()).hexdigest()
    found = store.find_user_by_confirmation_token_hash(digest)
    if not found or found.get("status") != "pending":
        raise ValueError("El enlace de confirmación no es válido o ya fue utilizado.")
    expires = found.get("confirmation_expires_at")
    now = _now()
    if expires is not None:
        if getattr(expires, "tzinfo", None) is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < now:
            raise ValueError("El enlace de confirmación venció. Inscríbete nuevamente para recibir otro.")
    updated = store.update_user(
        str(found.get("_id") or found.get("id")),
        {
            "status": "approved",
            "approved_at": now,
            "confirmation_token_hash": None,
            "confirmation_expires_at": None,
        },
    )
    public = store._public_user(updated or found)
    if not public:
        raise ValueError("No se pudo activar la cuenta.")
    return public


def authenticate(store, email: str, password: str) -> dict[str, Any]:
    clean = normalize_email(email)
    if not valid_login(clean):
        raise ValueError("Usuario o clave incorrectos.")
    found = store.find_user_by_email(clean)
    if not found or not verify_password(password, found.get("password_hash")):
        raise ValueError("Usuario o clave incorrectos.")
    status = found.get("status")
    if status == "pending":
        raise ValueError("Confirma tu correo antes de entrar.")
    if status == "invited":
        raise ValueError("El administrador ya aceptó tu email. Completa la inscripción.")
    if status != "approved":
        raise ValueError("El administrador no aceptó ese email.")
    public = store._public_user(found)
    if not public:
        raise ValueError("Usuario o clave incorrectos.")
    return public


def create_password_reset(store, email: str) -> tuple[dict[str, Any] | None, str]:
    """Crea un token de un solo uso. El caller nunca debe revelar si la cuenta existe."""
    clean = normalize_email(email)
    if not valid_email(clean):
        return None, ""
    found = store.find_user_by_email(clean)
    if not found or found.get("status") != "approved" or not found.get("password_hash"):
        return None, ""
    requested = found.get("password_reset_requested_at")
    if requested is not None:
        if getattr(requested, "tzinfo", None) is None:
            requested = requested.replace(tzinfo=timezone.utc)
        if requested > _now() - timedelta(seconds=60):
            return found, ""
    token = secrets.token_urlsafe(32)
    now = _now()
    updated = store.update_user(
        str(found.get("_id") or found.get("id")),
        {
            "password_reset_token_hash": hashlib.sha256(token.encode()).hexdigest(),
            "password_reset_expires_at": now + timedelta(minutes=PASSWORD_RESET_MINUTES),
            "password_reset_requested_at": now,
        },
    )
    return updated or found, token


def reset_password(store, token: str, password: str) -> dict[str, Any]:
    clean = str(token or "").strip()
    if len(password or "") < 8:
        raise ValueError("La nueva clave debe tener al menos 8 caracteres.")
    if not clean:
        raise ValueError("El enlace para cambiar la clave no es válido.")
    found = store.find_user_by_password_reset_token_hash(hashlib.sha256(clean.encode()).hexdigest())
    if not found:
        raise ValueError("El enlace para cambiar la clave no es válido o ya fue utilizado.")
    expires = found.get("password_reset_expires_at")
    if expires is None:
        raise ValueError("El enlace para cambiar la clave no es válido o ya fue utilizado.")
    if getattr(expires, "tzinfo", None) is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < _now():
        raise ValueError("El enlace para cambiar la clave venció. Solicita uno nuevo.")
    updated = store.update_user(
        str(found.get("_id") or found.get("id")),
        {
            "password_hash": hash_password(password),
            "password_reset_token_hash": None,
            "password_reset_expires_at": None,
            "password_changed_at": _now(),
        },
    )
    public = store._public_user(updated or found)
    if not public:
        raise ValueError("No se pudo cambiar la clave.")
    return public


def change_password(store, user_id: str, current_password: str, new_password: str) -> dict[str, Any]:
    found = store.find_user_by_id(user_id)
    if not found or not verify_password(current_password or "", found.get("password_hash")):
        raise ValueError("La clave actual no es correcta.")
    if len(new_password or "") < 8:
        raise ValueError("La nueva clave debe tener al menos 8 caracteres.")
    if current_password == new_password:
        raise ValueError("La nueva clave debe ser distinta de la actual.")
    updated = store.update_user(
        user_id,
        {
            "password_hash": hash_password(new_password),
            "password_reset_token_hash": None,
            "password_reset_expires_at": None,
            "password_changed_at": _now(),
        },
    )
    public = store._public_user(updated or found)
    if not public:
        raise ValueError("No se pudo cambiar la clave.")
    return public


def invite_email(store, email: str, *, admin: bool = False) -> dict[str, Any]:
    """El administrador acepta un email: si ya se inscribió, lo aprueba; si no, queda invitado."""
    clean = normalize_email(email)
    if not valid_email(clean):
        raise ValueError("Escribe un email válido.")
    found = store.find_user_by_email(clean)
    fields = {
        "status": "approved" if found and found.get("password_hash") else "invited",
        "approved_at": _now(),
    }
    if admin:
        fields["role"] = "admin"
    if found:
        updated = store.update_user(str(found.get("_id") or found.get("id")), fields)
        return store._public_user(updated or found)
    created = store.insert_user({"email": clean, "name": "", "role": "admin" if admin else "user", **fields})
    return store._public_user(created)


def set_user_status(store, user_id: str, status: str, *, actor_id: str | None = None) -> dict[str, Any]:
    if status not in {"approved", "rejected", "pending"}:
        raise ValueError("Estado inválido.")
    found = store.find_user_by_id(user_id)
    if not found:
        raise ValueError("No está ese usuario.")
    if str(found.get("_id") or found.get("id")) == str(actor_id or "") and status != "approved":
        raise ValueError("No puedes rechazar tu propia cuenta.")
    fields: dict[str, Any] = {"status": status}
    if status == "approved":
        fields["approved_at"] = _now()
    updated = store.update_user(user_id, fields)
    public = store._public_user(updated or found)
    if not public:
        raise ValueError("No está ese usuario.")
    return public


def bootstrap_admin_password() -> str:
    return admin_password()
