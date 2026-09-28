from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from retail.batch.config import load_schedule, save_schedule
from retail.store_categories import enabled_group_ids

BEGIN = "# retail-ofertas-begin"
END = "# retail-ofertas-end"
HOST_HINT = (
    "Horario guardado. En BMAX el cron corre en el host: prod-menu opción 8 "
    "(también se reinstala en cada deploy)."
)


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def cron_command(grupo: str | None = None) -> str:
    root = project_root()
    script = root / "scripts" / "ofertas-diarias.sh"
    if grupo:
        return f"{script} {grupo}"
    return f"{script}"


def stagger_minutes(schedule: dict | None = None) -> int:
    block = (schedule or {}).get("groups") or {}
    try:
        value = int(block.get("stagger_minutes") if block.get("stagger_minutes") is not None else 45)
    except (TypeError, ValueError):
        value = 45
    return max(5, min(180, value))


def group_slots(schedule: dict | None = None) -> list[tuple[str, int, int]]:
    """(grupo, hour, minute) escalonados desde hour/minute de programacion.json."""
    data = schedule or load_schedule()
    groups = enabled_group_ids(data)
    if not groups:
        return []
    base_h = int(6 if data.get("hour") is None else data["hour"])
    base_m = int(0 if data.get("minute") is None else data["minute"])
    step = stagger_minutes(data)
    slots: list[tuple[str, int, int]] = []
    total = base_h * 60 + base_m
    for grupo in groups:
        hour = (total // 60) % 24
        minute = total % 60
        slots.append((grupo, hour, minute))
        total += step
    return slots


def cron_line(hour: int, minute: int, grupo: str | None = None) -> str:
    return f"{minute} {hour} * * * {cron_command(grupo)}"


def cron_lines(schedule: dict | None = None) -> list[str]:
    data = schedule or load_schedule()
    mode = ((data.get("groups") or {}).get("mode") or "per_group").strip().lower()
    if mode == "single":
        return [cron_line(int(data["hour"]), int(data["minute"]))]
    return [cron_line(hour, minute, grupo) for grupo, hour, minute in group_slots(data)]


def _in_container() -> bool:
    return Path("/.dockerenv").exists()


def _use_host_cron() -> bool:
    return _in_container() or shutil.which("crontab") is None


def current_crontab() -> str:
    try:
        result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    except OSError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout


def apply_schedule(data: dict, repo=None) -> dict:
    saved = save_schedule(data, repo)
    lines = cron_lines(saved)
    saved["line"] = lines[0] if lines else cron_line(saved["hour"], saved["minute"])
    saved["lines"] = lines
    saved["command"] = cron_command()
    saved["cron_error"] = None
    if _use_host_cron():
        saved["backend"] = "host"
        saved["installed"] = False
        saved["hint"] = HOST_HINT if saved["enabled"] else (
            "Horario guardado (corrida diaria desactivada). "
            "El wrapper del host omite el batch si enabled=false."
        )
        return saved
    saved["backend"] = "crontab"
    try:
        text = current_crontab()
        cleaned = _strip_block(text)
        if saved["enabled"] and lines:
            block = BEGIN + "\n" + "\n".join(lines) + "\n" + END + "\n"
            cleaned = cleaned.rstrip() + ("\n" if cleaned.strip() else "") + block
        _install(cleaned)
        saved["installed"] = bool(saved["enabled"] and lines)
    except RuntimeError as exc:
        saved["installed"] = False
        saved["cron_error"] = str(exc)
    return saved


def schedule_status(repo=None) -> dict:
    saved = load_schedule(repo)
    lines = cron_lines(saved)
    saved["line"] = lines[0] if lines else cron_line(saved["hour"], saved["minute"])
    saved["lines"] = lines
    saved["command"] = cron_command()
    if _use_host_cron():
        saved["backend"] = "host"
        saved["installed"] = False
        saved["hint"] = HOST_HINT
        return saved
    crontab = current_crontab()
    saved["backend"] = "crontab"
    saved["installed"] = BEGIN in crontab and any(
        cron_command(grupo) in crontab for grupo, _, _ in group_slots(saved)
    )
    return saved


def _strip_block(text: str) -> str:
    lines = text.splitlines()
    kept: list[str] = []
    skip = False
    for line in lines:
        if line.strip() == BEGIN:
            skip = True
            continue
        if line.strip() == END:
            skip = False
            continue
        if not skip:
            kept.append(line)
    return "\n".join(kept).rstrip() + ("\n" if kept else "")


def _install(text: str) -> None:
    try:
        result = subprocess.run(["crontab", "-"], input=text, capture_output=True, text=True)
    except OSError as exc:
        raise RuntimeError(f"No se pudo ejecutar crontab: {exc}") from exc
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "No se pudo actualizar crontab")
