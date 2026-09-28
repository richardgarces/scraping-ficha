from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from retail.notification_preferences import normalize_preferences
from retail.web.deps import current_user, repo_or_503
from retail.web_push import MAX_SUBSCRIPTIONS, normalize_subscription, vapid_keys

router = APIRouter()


def _user_document(request: Request, store):
    user = current_user(request, store, required=True) or {}
    document = store.find_user_by_id(str(user.get("id") or ""))
    if not document:
        raise HTTPException(status_code=404, detail="No se encontró la cuenta.")
    return user, document


@router.get("/api/account/push")
def push_settings(request: Request) -> dict:
    store = repo_or_503()
    try:
        _, document = _user_document(request, store)
        return {
            "supported": True,
            "public_key": vapid_keys(store)["public_key"],
            "subscriptions": len(document.get("push_subscriptions") or []),
        }
    finally:
        store.close()


@router.post("/api/account/push")
async def save_push_subscription(request: Request) -> dict:
    try:
        subscription = normalize_subscription(await request.json())
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    store = repo_or_503()
    try:
        user, document = _user_document(request, store)
        existing = [
            item for item in (document.get("push_subscriptions") or [])
            if isinstance(item, dict) and item.get("endpoint") != subscription["endpoint"]
        ]
        subscriptions = ([subscription] + existing)[:MAX_SUBSCRIPTIONS]
        preferences = normalize_preferences(document.get("notification_preferences"))
        preferences["channels"] = list(dict.fromkeys([*preferences["channels"], "push"]))
        if not store.update_user_fields(str(user.get("id") or ""), {
            "push_subscriptions": subscriptions,
            "notification_preferences": preferences,
        }):
            raise HTTPException(status_code=404, detail="No se encontró la cuenta.")
        return {"ok": True, "subscriptions": len(subscriptions)}
    finally:
        store.close()


@router.delete("/api/account/push")
async def remove_push_subscription(request: Request) -> dict:
    body = await request.json()
    endpoint = str((body if isinstance(body, dict) else {}).get("endpoint") or "").strip()
    if not endpoint:
        raise HTTPException(status_code=400, detail="Falta el dispositivo que se debe desactivar.")
    store = repo_or_503()
    try:
        user, document = _user_document(request, store)
        subscriptions = [
            item for item in (document.get("push_subscriptions") or [])
            if isinstance(item, dict) and item.get("endpoint") != endpoint
        ]
        fields = {"push_subscriptions": subscriptions}
        if not subscriptions:
            preferences = normalize_preferences(document.get("notification_preferences"))
            preferences["channels"] = [item for item in preferences["channels"] if item != "push"]
            fields["notification_preferences"] = preferences
        store.update_user_fields(str(user.get("id") or ""), fields)
        return {"ok": True, "subscriptions": len(subscriptions)}
    finally:
        store.close()
