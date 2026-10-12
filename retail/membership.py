"""Membresía mensual y cupos de alertas / seguimiento.

Roles:
  - ``admin``: sin cupo práctico (límite alto documentado)
  - ``paid``: usuario de pago mientras ``membership_expires_at`` esté vigente
  - ``user``: cuenta normal (cupo bajo)

La membresía vive en el documento de ``users`` (campos ``membership_*``).
Un mes de regalo extiende ``membership_expires_at`` desde ``max(ahora, vencimiento)``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

ROLE_ADMIN = "admin"
ROLE_PAID = "paid"
ROLE_USER = "user"
ROLES = frozenset({ROLE_ADMIN, ROLE_PAID, ROLE_USER})

PLAN_MONTHLY = "monthly"
SOURCE_GIFT = "gift"
SOURCE_PAID = "paid"
SOURCE_ADMIN = "admin"
SOURCE_PROMO = "promo"

MEMBERSHIP_DAYS = 30
# Admin: sin límite práctico; tope alto por si hace falta acotar abuso accidental.
ADMIN_ALERT_LIMIT = 10_000
ALERT_LIMITS = {
    ROLE_USER: 3,
    ROLE_PAID: 20,
    ROLE_ADMIN: ADMIN_ALERT_LIMIT,
}

LIMIT_CODE = "alert_limit"
UPGRADE_PATH = "/siguiendo#membresia"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def normalize_role(value: Any) -> str:
    role = str(value or ROLE_USER).strip().lower()
    if role in ROLES:
        return role
    return ROLE_USER


def membership_expires_at(document: dict[str, Any] | None) -> datetime | None:
    return _as_utc((document or {}).get("membership_expires_at"))


def membership_active(document: dict[str, Any] | None, *, now: datetime | None = None) -> bool:
    """True si la membresía de pago/regalo sigue vigente."""
    doc = document or {}
    if normalize_role(doc.get("role")) == ROLE_ADMIN:
        return True
    expires = membership_expires_at(doc)
    if expires is None:
        return False
    return expires > (now or _now())


def effective_tier(document: dict[str, Any] | None, *, now: datetime | None = None) -> str:
    """Tier para cupos: admin > paid vigente > user."""
    doc = document or {}
    role = normalize_role(doc.get("role"))
    if role == ROLE_ADMIN:
        return ROLE_ADMIN
    if membership_active(doc, now=now):
        return ROLE_PAID
    return ROLE_USER


def alert_limit_for(document: dict[str, Any] | None, *, now: datetime | None = None) -> int:
    return int(ALERT_LIMITS.get(effective_tier(document, now=now), ALERT_LIMITS[ROLE_USER]))


def has_advanced_account_prefs(document: dict[str, Any] | None, *, now: datetime | None = None) -> bool:
    """Filtros de correo, umbrales y tiendas preferidas/excluidas: paid vigente o admin."""
    return effective_tier(document, now=now) in {ROLE_PAID, ROLE_ADMIN}


def count_active_price_alerts(repo: Any, user_id: str) -> int:
    user_id = str(user_id or "").strip()
    if not user_id:
        return 0
    if hasattr(repo, "count_price_alerts"):
        try:
            return max(0, int(repo.count_price_alerts(user_id)))
        except Exception:
            pass
    alerts = getattr(repo, "price_alerts", None)
    if alerts is None:
        return 0
    try:
        return int(alerts.count_documents({"user_id": user_id, "active": True}))
    except Exception:
        return 0


def membership_public(document: dict[str, Any] | None, *, now: datetime | None = None) -> dict[str, Any]:
    """Resumen seguro para API / sesión (sin tokens)."""
    doc = document or {}
    current = now or _now()
    active = membership_active(doc, now=current)
    tier = effective_tier(doc, now=current)
    expires = membership_expires_at(doc)
    starts = _as_utc(doc.get("membership_starts_at"))
    source = str(doc.get("membership_source") or "").strip() or None
    plan = str(doc.get("membership_plan") or "").strip() or None
    if active and not plan:
        plan = PLAN_MONTHLY
    if normalize_role(doc.get("role")) == ROLE_ADMIN:
        # Admin no compra membresía; el resumen indica privilegio completo.
        return {
            "active": True,
            "tier": ROLE_ADMIN,
            "plan": None,
            "source": None,
            "starts_at": starts.isoformat() if starts else None,
            "expires_at": None,
            "gift_months": int(doc.get("membership_gift_months") or 0),
            "alert_limit": alert_limit_for(doc, now=current),
            "upgrade_path": UPGRADE_PATH,
        }
    return {
        "active": active,
        "tier": tier,
        "plan": plan if active else (plan or None),
        "source": source if (active or source) else None,
        "starts_at": starts.isoformat() if starts else None,
        "expires_at": expires.isoformat() if expires else None,
        "gift_months": int(doc.get("membership_gift_months") or 0),
        "alert_limit": alert_limit_for(doc, now=current),
        "upgrade_path": UPGRADE_PATH,
    }


def sync_expired_role(store: Any, document: dict[str, Any]) -> dict[str, Any]:
    """Si era paid y venció, vuelve a ``user`` (no toca admin)."""
    role = normalize_role(document.get("role"))
    if role != ROLE_PAID:
        return document
    if membership_active(document):
        return document
    user_id = str(document.get("_id") or document.get("id") or "")
    if not user_id or not hasattr(store, "update_user"):
        document = dict(document)
        document["role"] = ROLE_USER
        return document
    updated = store.update_user(user_id, {"role": ROLE_USER})
    return updated or {**document, "role": ROLE_USER}


def alert_quota(
    repo: Any,
    user: dict[str, Any],
    *,
    store: str | None = None,
    product_id: str | None = None,
) -> dict[str, Any]:
    """Cupo actual. Si ya sigue ese producto, ``can_add`` es True sin consumir cupo."""
    user_id = str(user.get("id") or user.get("_id") or "")
    raw = user
    if hasattr(repo, "find_user_by_id") and user_id:
        try:
            found = repo.find_user_by_id(user_id)
            if found:
                raw = found
                raw = sync_expired_role(repo, raw)
        except Exception:
            raw = user
    limit = alert_limit_for(raw)
    count = count_active_price_alerts(repo, user_id)
    already = False
    if store and product_id and hasattr(repo, "get_price_alert") and user_id:
        try:
            already = bool(repo.get_price_alert(user_id, store, product_id))
        except Exception:
            already = False
    can_add = already or count < limit
    membership = membership_public(raw)
    return {
        "can_add": can_add,
        "already": already,
        "count": count,
        "limit": limit,
        "tier": membership["tier"],
        "membership": membership,
        "upgrade": not can_add and membership["tier"] == ROLE_USER,
        "upgrade_path": UPGRADE_PATH,
    }


def limit_error_detail(quota: dict[str, Any]) -> dict[str, Any]:
    limit = int(quota.get("limit") or ALERT_LIMITS[ROLE_USER])
    count = int(quota.get("count") or 0)
    if quota.get("tier") == ROLE_PAID:
        message = (
            f"Llegaste al máximo de {limit} productos con alerta en la membresía. "
            "Quita alguna alerta en Siguiendo para agregar otra."
        )
    else:
        message = (
            f"Con la cuenta gratuita puedes seguir hasta {limit} productos "
            f"(llevas {count}). Activa la membresía para seguir hasta "
            f"{ALERT_LIMITS[ROLE_PAID]}."
        )
    return {
        "code": LIMIT_CODE,
        "message": message,
        "limit": limit,
        "count": count,
        "tier": quota.get("tier") or ROLE_USER,
        "upgrade": bool(quota.get("upgrade")),
        "upgrade_path": quota.get("upgrade_path") or UPGRADE_PATH,
    }


def check_can_activate_alert(
    repo: Any,
    user: dict[str, Any],
    *,
    store: str | None = None,
    product_id: str | None = None,
) -> tuple[bool, dict[str, Any] | str]:
    """Combina canal usable + cupo de membresía."""
    from retail.user_alert_list import user_can_activate_alert

    ok, detail = user_can_activate_alert(user)
    if not ok:
        return False, detail
    quota = alert_quota(repo, user, store=store, product_id=product_id)
    if not quota["can_add"]:
        return False, limit_error_detail(quota)
    return True, quota


def _extend_expiry(current: datetime | None, *, months: int, now: datetime) -> datetime:
    months = max(1, int(months))
    base = current if current and current > now else now
    return base + timedelta(days=MEMBERSHIP_DAYS * months)


def grant_membership(
    store: Any,
    user_id: str,
    *,
    months: int = 1,
    source: str = SOURCE_GIFT,
    actor_id: str | None = None,
    keep_admin_role: bool = True,
) -> dict[str, Any]:
    """Activa o extiende membresía mensual. Devuelve usuario público enriquecido."""
    found = store.find_user_by_id(user_id)
    if not found:
        raise ValueError("No está ese usuario.")
    months = max(1, min(24, int(months)))
    now = _now()
    current_exp = membership_expires_at(found)
    expires = _extend_expiry(current_exp, months=months, now=now)
    role = normalize_role(found.get("role"))
    fields: dict[str, Any] = {
        "membership_plan": PLAN_MONTHLY,
        "membership_source": source,
        "membership_starts_at": _as_utc(found.get("membership_starts_at")) or now,
        "membership_expires_at": expires,
        "membership_updated_at": now,
    }
    if actor_id:
        fields["membership_granted_by"] = str(actor_id)
    if source in {SOURCE_GIFT, SOURCE_PROMO}:
        fields["membership_gift_granted_at"] = now
        fields["membership_gift_months"] = int(found.get("membership_gift_months") or 0) + months
    if role != ROLE_ADMIN or not keep_admin_role:
        if role != ROLE_ADMIN:
            fields["role"] = ROLE_PAID
    updated = store.update_user(user_id, fields)
    public = store._public_user(updated or found)
    if not public:
        raise ValueError("No está ese usuario.")
    return public


def grant_gift_month(
    store: Any,
    user_id: str,
    *,
    months: int = 1,
    actor_id: str | None = None,
) -> dict[str, Any]:
    """Admin u operación interna: 1 mes de regalo (extensible)."""
    return grant_membership(
        store,
        user_id,
        months=months,
        source=SOURCE_GIFT,
        actor_id=actor_id,
    )


def set_user_role(
    store: Any,
    user_id: str,
    role: str,
    *,
    actor_id: str | None = None,
) -> dict[str, Any]:
    """Cambia rol. Pasar a paid sin vencimiento otorga 1 mes admin."""
    wanted = normalize_role(role)
    if wanted not in ROLES:
        raise ValueError("Rol inválido.")
    found = store.find_user_by_id(user_id)
    if not found:
        raise ValueError("No está ese usuario.")
    if str(found.get("_id") or found.get("id")) == str(actor_id or "") and wanted != ROLE_ADMIN:
        if normalize_role(found.get("role")) == ROLE_ADMIN:
            raise ValueError("No puedes quitarte el rol de administrador.")
    if wanted == ROLE_PAID:
        return grant_membership(
            store,
            user_id,
            months=1,
            source=SOURCE_ADMIN,
            actor_id=actor_id,
        )
    now = _now()
    fields: dict[str, Any] = {"role": wanted, "membership_updated_at": now}
    if wanted == ROLE_USER:
        # Quitar cupo de pago de inmediato (se conserva historial de gift_months).
        fields["membership_expires_at"] = now - timedelta(seconds=1)
        fields["membership_source"] = None
    if wanted == ROLE_ADMIN:
        fields["status"] = "approved"
        fields.setdefault("approved_at", now)
    updated = store.update_user(user_id, fields)
    public = store._public_user(updated or found)
    if not public:
        raise ValueError("No está ese usuario.")
    return public


def redeem_promo_code(store: Any, user_id: str, code: str) -> dict[str, Any]:
    """Canjea un código de «1 mes de regalo». Un código por cuenta."""
    import os

    clean = str(code or "").strip().upper()
    if not clean or len(clean) > 64:
        raise ValueError("Código inválido.")
    allowed_raw = os.environ.get("RETAIL_MEMBERSHIP_PROMO_CODES") or "REGALO1MES"
    allowed = {part.strip().upper() for part in allowed_raw.split(",") if part.strip()}
    if clean not in allowed:
        raise ValueError("Ese código no es válido.")
    found = store.find_user_by_id(user_id)
    if not found:
        raise ValueError("No está ese usuario.")
    if found.get("membership_promo_code"):
        raise ValueError("Ya usaste un código de regalo en esta cuenta.")
    if normalize_role(found.get("role")) == ROLE_ADMIN:
        raise ValueError("La cuenta de administrador no necesita membresía.")
    public = grant_membership(
        store,
        user_id,
        months=1,
        source=SOURCE_PROMO,
        actor_id=None,
    )
    store.update_user(user_id, {"membership_promo_code": clean})
    refreshed = store.find_user_by_id(user_id) or found
    return store._public_user(refreshed) or public
