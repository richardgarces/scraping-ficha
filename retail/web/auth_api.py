from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from datetime import datetime, timedelta, timezone
from html import escape
import hashlib
import os
import secrets
from urllib.parse import quote

from retail import users as accounts
from retail.batch.alerts import _secret, _telegram_api, send_email
from retail.auth import normalize_email
from retail.registry import group_of, list_stores
from retail.search import connect_repo
from retail.web.deps import clear_session, current_user, repo_or_503, set_session
from retail.notification_preferences import normalize_preferences
from retail.predictive_alerts import anticipated_drop_validation_status, predictive_validation_status
from retail.store_categories import list_store_categories

router = APIRouter()

TELEGRAM_LINK_MINUTES = 30
TELEGRAM_LINK_PREFIX = "precios_"
PASSWORD_RESET_MESSAGE = "Enviaremos un enlace para cambiar la clave."


def _store_options() -> list[dict]:
    rows = []
    for spec in list_stores():
        group_id, group_title, group_order = group_of(spec.id, spec.group)
        rows.append({"id": spec.id, "title": spec.title, "group": group_id, "group_title": group_title, "group_order": group_order})
    rows.sort(key=lambda item: (item["group_order"], item["title"].casefold(), item["id"]))
    return rows


def _normalize_store_preferences(value: object) -> list[str]:
    allowed = {item.id for item in list_stores()}
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item).strip().lower() for item in value if str(item).strip().lower() in allowed))


def _telegram_account(document: dict) -> tuple[str, bool]:
    """Devuelve el valor visible y si existe un chat privado verificable."""
    chat_id = str(document.get("telegram_chat_id") or "").strip()
    username = str(document.get("telegram_username") or "").strip()
    connected = bool(chat_id) and chat_id.lstrip("-").isdigit()
    return username or chat_id, connected


def _normalize_telegram_username(value: object) -> str:
    text = str(value or "").strip()
    if text and not text.lstrip("-").isdigit() and not text.startswith("@"):
        text = f"@{text}"
    return text


def _telegram_token() -> str:
    token = _secret("TELEGRAM_BOT_TOKEN", "telegram_bot_token").strip()
    if not token:
        raise HTTPException(status_code=503, detail="El bot de Telegram no está configurado.")
    return token


def _pending_telegram_links(store) -> dict[str, dict]:
    now = datetime.now(timezone.utc)
    users = getattr(store, "users", None)
    if users is None or not hasattr(users, "find"):
        return {}
    try:
        rows = users.find({
            "telegram_link_token_hash": {"$exists": True, "$ne": ""},
            "telegram_link_expires_at": {"$gt": now},
        })
    except Exception:
        return {}
    return {
        str(row.get("telegram_link_token_hash")): row
        for row in rows
        if row.get("telegram_link_token_hash")
    }


def _sync_telegram_links(store, token: str) -> int:
    """Vincula mensajes /start pendientes con la cuenta que creó el enlace."""
    pending = _pending_telegram_links(store)
    if not pending:
        return 0
    response = _telegram_api(token, "getUpdates", {
        "limit": "100", "timeout": "0", "allowed_updates": '["message"]',
    })
    if not response.get("ok"):
        detail = response.get("description") or response.get("error") or "sin respuesta"
        raise HTTPException(status_code=502, detail=f"Telegram no respondió correctamente: {detail}")
    linked = 0
    max_update_id: int | None = None
    for update in response.get("result") or []:
        update_id = update.get("update_id")
        if isinstance(update_id, int):
            max_update_id = update_id if max_update_id is None else max(max_update_id, update_id)
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        sender = message.get("from") or {}
        text = str(message.get("text") or "").strip()
        parts = text.split(maxsplit=1)
        command = parts[0].split("@", 1)[0] if parts else ""
        payload = parts[1] if len(parts) == 2 else ""
        if command != "/start" or not payload.startswith(TELEGRAM_LINK_PREFIX):
            continue
        raw = payload[len(TELEGRAM_LINK_PREFIX):]
        digest = hashlib.sha256(raw.encode()).hexdigest()
        document = pending.get(digest)
        chat_id = str(chat.get("id") or "")
        if not document or chat.get("type") != "private" or not chat_id.lstrip("-").isdigit():
            continue
        username = str(sender.get("username") or chat.get("username") or "").strip()
        fields = {
            "telegram_chat_id": chat_id,
            "telegram_connected_at": datetime.now(timezone.utc),
        }
        if username:
            fields["telegram_username"] = f"@{username.lstrip('@')}"
        store.update_user_fields(
            str(document.get("_id") or document.get("id") or ""), fields,
            unset=("telegram_link_token_hash", "telegram_link_expires_at"),
        )
        linked += 1
    # Todos los tokens vigentes fueron evaluados antes de avanzar el cursor.
    if max_update_id is not None:
        _telegram_api(token, "getUpdates", {"offset": str(max_update_id + 1), "limit": "1", "timeout": "0"})
    return linked


def _predictive_status(store) -> dict:
    return {
        **predictive_validation_status(store),
        "anticipated": anticipated_drop_validation_status(store),
    }


@router.post("/api/auth/register")
async def register(request: Request):
    body = await request.json()
    store = repo_or_503()
    try:
        try:
            user = accounts.signup(
                store,
                body.get("email") or "",
                body.get("password") or "",
                body.get("name") or "",
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        token = user.pop("_confirmation_token", "") if user else ""
        payload: dict = {"user": user}
        if user and user.get("status") == "approved":
            out = JSONResponse(payload)
            set_session(out, user["id"])
            return out
        public_site = os.environ.get("PUBLIC_SITE_URL", "https://precios.meincart.cl").rstrip("/")
        confirm_url = f"{public_site}/api/auth/confirm?token={quote(token, safe='')}"
        safe_url = escape(confirm_url, quote=True)
        sent = send_email(
            user.get("email") or "",
            "Confirma tu cuenta en Precios",
            f"Confirma tu cuenta abriendo este enlace:\n\n{confirm_url}\n\nEl enlace vence en 24 horas.",
            html=(
                '<html><body><h2>Confirma tu cuenta</h2>'
                '<p>Presiona el botón para activar tu cuenta y comenzar a recibir alertas.</p>'
                f'<p><a href="{safe_url}" style="display:inline-block;padding:12px 20px;'
                'background:#176b55;color:#fff;text-decoration:none;border-radius:8px">Confirmar</a></p>'
                '<p>Este enlace vence en 24 horas.</p></body></html>'
            ),
        )
        if not sent:
            raise HTTPException(status_code=503, detail="La cuenta quedó pendiente, pero no se pudo enviar el correo de confirmación. Intenta inscribirte nuevamente.")
        payload["message"] = "Te enviamos un correo. Confirma tu cuenta desde el botón del mensaje para poder entrar y recibir alertas."
        return payload
    finally:
        store.close()


@router.get("/api/auth/confirm")
def confirm(token: str = ""):
    store = repo_or_503()
    try:
        try:
            accounts.confirm_email(store, token)
        except ValueError as exc:
            return RedirectResponse(f"/entrar?error={quote(str(exc))}", status_code=303)
        return RedirectResponse("/entrar?confirmado=1", status_code=303)
    finally:
        store.close()


@router.post("/api/auth/login")
async def login(request: Request):
    body = await request.json()
    store = repo_or_503()
    try:
        try:
            user = accounts.authenticate(store, body.get("email") or "", body.get("password") or "")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        out = JSONResponse({"user": user})
        set_session(out, user["id"])
        return out
    finally:
        store.close()


@router.post("/api/auth/logout")
def logout():
    out = JSONResponse({"ok": True})
    clear_session(out)
    return out


@router.post("/api/auth/password/forgot")
async def forgot_password(request: Request) -> dict:
    body = await request.json()
    store = repo_or_503()
    try:
        document, token = accounts.create_password_reset(store, normalize_email(body.get("email")))
        if document and token:
            public_site = os.environ.get("PUBLIC_SITE_URL", "https://precios.meincart.cl").rstrip("/")
            reset_url = f"{public_site}/entrar?modo=restablecer&token={quote(token, safe='')}"
            safe_url = escape(reset_url, quote=True)
            send_email(
                document.get("email") or "",
                "Cambia tu clave de Precios",
                f"Abre este enlace para cambiar tu clave:\n\n{reset_url}\n\nEl enlace vence en 30 minutos y solo funciona una vez.",
                html=(
                    '<html><body style="font-family:Arial,sans-serif;color:#14213d">'
                    '<h2>Cambia tu clave</h2><p>Recibimos una solicitud para cambiar la clave de tu cuenta.</p>'
                    f'<p><a href="{safe_url}" style="display:inline-block;padding:12px 20px;background:#258fdf;color:#fff;text-decoration:none;border-radius:10px">Cambiar clave</a></p>'
                    '<p>El enlace vence en 30 minutos y solo funciona una vez. Si no lo pediste, ignora este mensaje.</p>'
                    '</body></html>'
                ),
            )
        return {"ok": True, "message": PASSWORD_RESET_MESSAGE}
    finally:
        store.close()


@router.post("/api/auth/password/reset")
async def finish_password_reset(request: Request):
    body = await request.json()
    store = repo_or_503()
    try:
        try:
            user = accounts.reset_password(store, body.get("token") or "", body.get("password") or "")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        out = JSONResponse({"ok": True, "user": user})
        set_session(out, user["id"])
        return out
    finally:
        store.close()


@router.put("/api/account/password")
async def update_password(request: Request):
    body = await request.json()
    store = repo_or_503()
    try:
        user = current_user(request, store, required=True) or {}
        try:
            updated = accounts.change_password(
                store,
                str(user.get("id") or ""),
                body.get("current_password") or "",
                body.get("new_password") or "",
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        out = JSONResponse({"ok": True, "user": updated})
        set_session(out, updated["id"])
        return out
    finally:
        store.close()


@router.get("/api/account/store-preferences")
def store_preferences(request: Request) -> dict:
    store = repo_or_503()
    try:
        user = current_user(request, store, required=True) or {}
        document = store.find_user_by_id(str(user.get("id") or "")) or {}
        return {
            "favorites": _normalize_store_preferences(document.get("favorite_stores")),
            "excluded": _normalize_store_preferences(document.get("excluded_stores")),
            "stores": _store_options(),
        }
    finally:
        store.close()


@router.put("/api/account/store-preferences")
async def update_store_preferences(request: Request) -> dict:
    body = await request.json()
    store = repo_or_503()
    try:
        user = current_user(request, store, required=True) or {}
        favorites = _normalize_store_preferences(body.get("favorites"))
        excluded = _normalize_store_preferences(body.get("excluded"))
        excluded_set = set(excluded)
        favorites = [item for item in favorites if item not in excluded_set]
        updated = store.update_user_fields(
            str(user.get("id") or ""),
            {"favorite_stores": favorites, "excluded_stores": excluded},
        )
        if not updated:
            raise HTTPException(status_code=404, detail="No se encontró la cuenta.")
        return {"favorites": favorites, "excluded": excluded, "stores": _store_options()}
    finally:
        store.close()


@router.get("/api/auth/me")
def me(request: Request) -> dict:
    store = connect_repo()
    if store is None:
        return {"user": None}
    try:
        return {"user": current_user(request, store)}
    finally:
        store.close()


@router.get("/api/account/notifications")
def notification_settings(request: Request) -> dict:
    store = repo_or_503()
    try:
        user = current_user(request, store, required=True) or {}
        document = store.find_user_by_id(str(user.get("id") or "")) or {}
        telegram, connected = _telegram_account(document)
        return {
            "preferences": normalize_preferences(document.get("notification_preferences")),
            "email": document.get("email") or user.get("email") or "",
            "telegram": telegram,
            "telegram_connected": connected,
            "notification_categories": [
                {"id": item["id"], "title": item["title"]}
                for item in list_store_categories(repo=store)
            ],
            "predictive": _predictive_status(store),
        }
    finally:
        store.close()


@router.put("/api/account/notifications")
async def update_notification_settings(request: Request) -> dict:
    body = await request.json()
    store = repo_or_503()
    try:
        user = current_user(request, store, required=True) or {}
        telegram = _normalize_telegram_username(body.get("telegram"))
        if len(telegram) > 100:
            raise HTTPException(status_code=400, detail="El usuario o chat de Telegram es demasiado largo.")
        preferences = normalize_preferences(body.get("preferences"))
        if "telegram" in preferences["channels"] and not telegram:
            raise HTTPException(status_code=400, detail="Indica tu usuario de Telegram y conecta el bot.")
        current = store.find_user_by_id(str(user.get("id") or "")) or {}
        fields = {"notification_preferences": preferences}
        unset: tuple[str, ...] = ()
        if telegram.lstrip("-").isdigit():
            fields["telegram_chat_id"] = telegram
        else:
            fields["telegram_username"] = telegram
            previous_username = _normalize_telegram_username(current.get("telegram_username"))
            current_chat = str(current.get("telegram_chat_id") or "").strip()
            if current_chat and (not current_chat.lstrip("-").isdigit() or telegram != previous_username):
                unset = ("telegram_chat_id",)
        updated = store.update_user_fields(str(user.get("id") or ""), fields, unset=unset)
        if not updated:
            raise HTTPException(status_code=404, detail="No se encontró la cuenta.")
        telegram_value, connected = _telegram_account(updated)
        return {
            "preferences": preferences,
            "email": updated.get("email") or "",
            "telegram": telegram_value,
            "telegram_connected": connected,
            "notification_categories": [
                {"id": item["id"], "title": item["title"]}
                for item in list_store_categories(repo=store)
            ],
            "predictive": _predictive_status(store),
        }
    finally:
        store.close()


@router.post("/api/account/telegram/link")
async def create_telegram_link(request: Request) -> dict:
    body = await request.json()
    store = repo_or_503()
    try:
        user = current_user(request, store, required=True) or {}
        username = _normalize_telegram_username(body.get("telegram"))
        if len(username) > 100:
            raise HTTPException(status_code=400, detail="El usuario de Telegram es demasiado largo.")
        token = _telegram_token()
        bot = _telegram_api(token, "getMe", {})
        bot_username = str((bot.get("result") or {}).get("username") or "").strip()
        if not bot.get("ok") or not bot_username:
            raise HTTPException(status_code=502, detail="No se pudo consultar el bot de Telegram.")
        link_token = secrets.token_urlsafe(18)
        fields = {
            "telegram_link_token_hash": hashlib.sha256(link_token.encode()).hexdigest(),
            "telegram_link_expires_at": datetime.now(timezone.utc) + timedelta(minutes=TELEGRAM_LINK_MINUTES),
        }
        if username:
            fields["telegram_username"] = username
        # La conexión actual sigue activa hasta verificar la nueva; así un enlace
        # vencido o una ventana bloqueada no corta alertas que ya funcionaban.
        updated = store.update_user_fields(str(user.get("id") or ""), fields)
        if not updated:
            raise HTTPException(status_code=404, detail="No se encontró la cuenta.")
        return {
            "url": f"https://t.me/{bot_username}?start={TELEGRAM_LINK_PREFIX}{link_token}",
            "bot_username": f"@{bot_username}",
            "expires_in": TELEGRAM_LINK_MINUTES * 60,
        }
    finally:
        store.close()


@router.post("/api/account/telegram/verify")
def verify_telegram_link(request: Request) -> dict:
    store = repo_or_503()
    try:
        user = current_user(request, store, required=True) or {}
        token = _telegram_token()
        _sync_telegram_links(store, token)
        document = store.find_user_by_id(str(user.get("id") or "")) or {}
        telegram, connected = _telegram_account(document)
        if not connected:
            raise HTTPException(
                status_code=409,
                detail="Aún no recibimos la conexión. Abre el bot, presiona Iniciar y vuelve a verificar.",
            )
        return {"ok": True, "telegram": telegram, "telegram_connected": True}
    finally:
        store.close()


@router.get("/api/users")
def list_users(request: Request) -> dict:
    store = repo_or_503()
    try:
        current_user(request, store, admin=True)
        return {"users": store.list_users()}
    finally:
        store.close()


@router.post("/api/users/accept")
async def accept_email(request: Request) -> dict:
    body = await request.json()
    store = repo_or_503()
    try:
        current_user(request, store, admin=True)
        try:
            user = accounts.invite_email(store, body.get("email") or "", admin=bool(body.get("admin")))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"user": user}
    finally:
        store.close()


@router.post("/api/users/{user_id}/status")
async def change_status(user_id: str, request: Request) -> dict:
    body = await request.json()
    store = repo_or_503()
    try:
        actor = current_user(request, store, admin=True)
        try:
            user = accounts.set_user_status(
                store,
                user_id,
                str(body.get("status") or ""),
                actor_id=(actor or {}).get("id"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"user": user}
    finally:
        store.close()
