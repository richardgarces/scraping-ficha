"""Errores de arranque y detención de las corridas por grupo."""

from __future__ import annotations

import os
from typing import Any

# sysexits.h EX_TEMPFAIL — el wrapper de cron reintenta sin tratarlo como fallo duro.
INTERRUPT_EXIT_CODE = 75

DEFAULT_INTERRUPT_RETRIES = 1
DEFAULT_INTERRUPT_RETRY_DELAY = 20.0


class GroupBatchBusy(RuntimeError):
    def __init__(self, group: str) -> None:
        super().__init__(f"Ya hay una corrida de {group} en curso.")


class GroupBatchPaused(RuntimeError):
    def __init__(self) -> None:
        super().__init__("Reanuda las corridas antes de iniciar un grupo.")


class GroupBatchIdle(RuntimeError):
    def __init__(self, group: str) -> None:
        super().__init__(f"No hay una corrida de {group} en curso.")


class GroupBatchStopped(Exception):
    def __init__(self) -> None:
        super().__init__("Corrida detenida por el administrador.")


class GroupBatchInterrupted(Exception):
    """Proceso/web reiniciado (deploy, SIGTERM) mientras el pool aún recibía trabajo."""

    def __init__(self, detail: str | None = None) -> None:
        text = (
            "Corrida interrumpida por reinicio del proceso (deploy/SIGTERM). "
            "Progreso guardado; reintento automático o la próxima corrida del cron continúa."
        )
        if detail:
            text = f"{text} ({detail})"
        super().__init__(text)


class GroupBatchNothingToResume(ValueError):
    def __init__(self, group: str) -> None:
        super().__init__(f"No hay progreso guardado para continuar {group}. Usa reiniciar.")


def is_executor_shutdown_error(exc: BaseException) -> bool:
    """True si concurrent.futures ya cerró el pool (atexit / shutdown)."""
    return isinstance(exc, RuntimeError) and "cannot schedule new futures after shutdown" in str(exc)


def interrupt_auto_retries() -> int:
    """Cuántos reintentos automáticos tras interrupción (0–2; default 1)."""
    raw = (os.environ.get("BATCH_INTERRUPT_RETRIES") or str(DEFAULT_INTERRUPT_RETRIES)).strip()
    try:
        return max(0, min(2, int(raw)))
    except ValueError:
        return DEFAULT_INTERRUPT_RETRIES


def interrupt_retry_delay_seconds(attempt: int = 0) -> float:
    """Espera antes del reintento ``attempt`` (0-based); base fija, backoff lineal."""
    raw = (os.environ.get("BATCH_INTERRUPT_RETRY_DELAY") or str(DEFAULT_INTERRUPT_RETRY_DELAY)).strip()
    try:
        base = max(1.0, float(raw))
    except ValueError:
        base = DEFAULT_INTERRUPT_RETRY_DELAY
    return base * (1 + max(0, int(attempt)))


def is_interrupt_status(status: str | None) -> bool:
    return (status or "").strip().lower() == "interrupted"


def batch_web_auto_resume_enabled() -> bool:
    raw = (os.environ.get("BATCH_WEB_AUTO_RESUME") or "1").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def batch_cursor_key(group: str) -> str:
    return f"batch_cursor:{group}"


def resume_product_id(run: dict[str, Any] | None) -> str | None:
    """Producto desde el cual retomar una corrida fallida o detenida."""
    if not run:
        return None
    current = str(run.get("current_id") or "").strip()
    if current:
        return current
    searches = run.get("searches") or []
    if not isinstance(searches, list) or not searches:
        return None
    last = searches[-1] if isinstance(searches[-1], dict) else {}
    found = str(last.get("id") or "").strip()
    return found or None


def raise_if_group_stopped(repo: Any, run_id: str | None) -> None:
    """Corta solo la corrida marcada. Las demás siguen en su propio documento."""
    if not repo or not run_id or not hasattr(repo, "group_stop_requested"):
        return
    if repo.group_stop_requested(run_id):
        raise GroupBatchStopped()
