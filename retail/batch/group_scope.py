"""Errores de arranque y detención de las corridas por grupo."""

from typing import Any


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


class GroupBatchNothingToResume(ValueError):
    def __init__(self, group: str) -> None:
        super().__init__(f"No hay progreso guardado para continuar {group}. Usa reiniciar.")


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
