"""Métricas de host (CPU / RAM / disco / temp / potencia) → Mongo `cyber_day_host_stats:{ip}`.

Usado por workers Cyber (Orange Pi) y reporters ligeros en BMAX/soyo
(`python -m retail.host_stats --once` / `--loop`).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import socket
import subprocess
import time
from datetime import datetime, timezone
from typing import Any

HOST_STATS_SETTING_PREFIX = "cyber_day_host_stats:"
HOST_STATS_REPORT_SECONDS = max(5.0, float(os.environ.get("CYBER_DAY_HOST_STATS_SECONDS") or os.environ.get("HOST_STATS_SECONDS") or "15"))
HOST_STATS_MAX_AGE = max(30, int(os.environ.get("CYBER_DAY_HOST_STATS_MAX_AGE") or os.environ.get("HOST_STATS_MAX_AGE") or "120"))
# Historial acotado en el mismo doc Mongo (cron ~1/min → ~24h con 1440 pts).
HOST_STATS_HISTORY_MAX = max(24, int(os.environ.get("HOST_STATS_HISTORY_MAX") or "1440"))
HOST_STATS_HISTORY_MAX_AGE = max(
    3600,
    int(os.environ.get("HOST_STATS_HISTORY_MAX_AGE") or str(24 * 3600)),
)
ALERT_DISK_WARN = max(50, int(os.environ.get("HOST_STATS_DISK_WARN") or "80"))
ALERT_DISK_HOT = max(ALERT_DISK_WARN, int(os.environ.get("HOST_STATS_DISK_HOT") or "90"))
ALERT_RAM_WARN = max(50, int(os.environ.get("HOST_STATS_RAM_WARN") or "90"))
ALERT_TEMP_WARN = max(40, int(os.environ.get("HOST_STATS_TEMP_WARN") or "70"))
ALERT_TEMP_HOT = max(ALERT_TEMP_WARN, int(os.environ.get("HOST_STATS_TEMP_HOT") or "85"))
# Docker reclaimable ≥ este umbral (GiB) → alerta informativa.
ALERT_DOCKER_RECLAIM_GIB = max(1.0, float(os.environ.get("HOST_STATS_DOCKER_RECLAIM_GIB") or "20"))
# Errores que disparan Telegram/email admin (no warn informativos ni docker reclaim).
HOST_NOTIFY_ALERT_CODES = frozenset({"stale", "no_data", "disk_hot", "temp_hot"})
HOST_ALERT_NOTIFY_STATE_KEY = "host_stats_alert_notify_state"
HOST_ALERT_NOTIFY_USER = "host_ops"
HOST_ALERT_NOTIFY_COOLDOWN_DAYS = max(
    1, int(os.environ.get("HOST_STATS_ALERT_COOLDOWN_DAYS") or "1")
)
# IP fija del host (containers Docker suelen ver otra IP).
HOST_IP = (
    (os.environ.get("HOST_STATS_HOST_IP") or "").strip()
    or (os.environ.get("CYBER_DAY_HOST_IP") or "").strip()
    or None
)
# Alias legacy: cyber_day y tests siguen pudiendo leer/parchear este nombre vía re-export.
CYBER_DAY_HOST_IP = HOST_IP

KNOWN_HOSTS: tuple[dict[str, str], ...] = (
    {
        "id": "bmax",
        "label": "BMAX",
        "ip": "192.168.1.198",
        "role": "Web, Mongo, Redis, Qdrant",
        "ssh": "ssh -p 2222 richard@192.168.1.198",
        "image": "/static/hosts/bmax.png",
    },
    {
        "id": "soyo",
        "label": "soyo",
        "ip": "192.168.1.197",
        "role": "Worker scrape",
        "ssh": "ssh richard@192.168.1.197",
        "image": "/static/hosts/soyo.jpg",
    },
    {
        "id": "orange_pi",
        "label": "Orange Pi",
        "ip": "192.168.1.90",
        "role": "Cyber Day scrape",
        "ssh": "ssh richard@192.168.1.90",
        "image": "/static/hosts/orange-pi.jpg",
    },
)

_CPU_SAMPLE: tuple[float, float] | None = None
_LAST_HOST_REPORT_AT = 0.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> str | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if value is None:
        return None
    return str(value)


def _read_proc_cpu_times() -> tuple[float, float] | None:
    """Devuelve (idle, total) de la primera línea cpu de /proc/stat."""
    try:
        with open("/proc/stat", encoding="utf-8") as fh:
            line = fh.readline()
    except OSError:
        return None
    if not line.startswith("cpu "):
        return None
    parts = line.split()
    try:
        nums = [float(x) for x in parts[1:8]]
    except (ValueError, IndexError):
        return None
    if len(nums) < 4:
        return None
    idle = nums[3] + (nums[4] if len(nums) > 4 else 0.0)
    total = sum(nums)
    return idle, total


def _cpu_percent_sample() -> float | None:
    """% CPU usado entre dos lecturas de /proc/stat (None en la 1.ª muestra)."""
    global _CPU_SAMPLE
    now = _read_proc_cpu_times()
    if now is None:
        return None
    prev = _CPU_SAMPLE
    _CPU_SAMPLE = now
    if prev is None:
        return None
    idle_d = now[0] - prev[0]
    total_d = now[1] - prev[1]
    if total_d <= 0:
        return None
    used = max(0.0, min(100.0, (1.0 - idle_d / total_d) * 100.0))
    return round(used, 1)


def _host_ip_guess() -> str | None:
    if HOST_IP:
        return HOST_IP
    if CYBER_DAY_HOST_IP:
        return CYBER_DAY_HOST_IP
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return None


_DOCKER_SIZE_RE = re.compile(
    r"^\s*([0-9]+(?:\.[0-9]+)?)\s*([kKmMgGtT]?i?[bB]?)\s*(?:\(|$)"
)


def _parse_docker_size(raw: str | None) -> int | None:
    """Convierte tamaños de `docker system df` ('13.33GB', '183.5GB (98%)') a bytes."""
    if not raw:
        return None
    text = str(raw).strip()
    match = _DOCKER_SIZE_RE.match(text)
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    unit = (match.group(2) or "B").lower().replace("i", "")
    factor = {
        "b": 1,
        "kb": 1000,
        "mb": 1000**2,
        "gb": 1000**3,
        "tb": 1000**4,
        "k": 1000,
        "m": 1000**2,
        "g": 1000**3,
        "t": 1000**4,
    }.get(unit, 1)
    return int(value * factor)


def _docker_df_from_text(text: str) -> dict[str, Any] | None:
    """Parsea líneas JSON de `docker system df --format '{{json .}}'`."""
    images_size = images_reclaim = volumes_size = volumes_reclaim = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        kind = str(row.get("Type") or row.get("type") or "").strip().lower()
        size = _parse_docker_size(str(row.get("Size") or ""))
        reclaim = _parse_docker_size(str(row.get("Reclaimable") or ""))
        if kind == "images":
            images_size, images_reclaim = size, reclaim
        elif kind in {"local volumes", "volumes"}:
            volumes_size, volumes_reclaim = size, reclaim
    if images_size is None and images_reclaim is None and volumes_size is None:
        return None
    reclaim_total = None
    parts = [x for x in (images_reclaim, volumes_reclaim) if x is not None]
    if parts:
        reclaim_total = sum(parts)
    return {
        "images_bytes": images_size,
        "images_reclaimable_bytes": images_reclaim,
        "volumes_bytes": volumes_size,
        "volumes_reclaimable_bytes": volumes_reclaim,
        "reclaimable_bytes": reclaim_total,
    }


def collect_docker_df() -> dict[str, Any] | None:
    """Resumen Docker (imágenes/volúmenes reclaimable). Env o CLI local."""
    injected = (os.environ.get("HOST_STATS_DOCKER_DF") or "").strip()
    if not injected:
        b64 = (os.environ.get("HOST_STATS_DOCKER_DF_B64") or "").strip()
        if b64:
            try:
                injected = base64.b64decode(b64).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                injected = ""
    if injected:
        parsed = _docker_df_from_text(injected)
        if parsed:
            return parsed
    try:
        proc = subprocess.run(
            ["docker", "system", "df", "--format", "{{json .}}"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        return None
    return _docker_df_from_text(proc.stdout)


def _uptime_seconds() -> float | None:
    try:
        with open("/proc/uptime", encoding="utf-8") as fh:
            first = fh.read().split()[0]
        return round(float(first), 1)
    except (OSError, IndexError, ValueError):
        return None


def _read_first_line(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.readline().strip()
        return text or None
    except OSError:
        return None


def _cpu_model_from_proc() -> str | None:
    """Modelo de CPU desde /proc/cpuinfo (x86 model name / ARM Hardware)."""
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as fh:
            model = hardware = processor = None
            for line in fh:
                if ":" not in line:
                    continue
                key, raw = line.split(":", 1)
                key_l = key.strip().lower()
                val = raw.strip()
                if not val:
                    continue
                if key_l == "model name" and not model:
                    model = val
                elif key_l == "hardware" and not hardware:
                    hardware = val
                elif key_l == "processor" and not processor and not val.isdigit():
                    processor = val
            return model or hardware or processor
    except OSError:
        return None


def _os_pretty_name() -> str | None:
    """PRETTY_NAME de /etc/os-release (p. ej. Ubuntu 24.04.1 LTS)."""
    try:
        with open("/etc/os-release", encoding="utf-8", errors="replace") as fh:
            data: dict[str, str] = {}
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, raw = line.split("=", 1)
                data[key] = raw.strip().strip('"')
        return data.get("PRETTY_NAME") or data.get("NAME")
    except OSError:
        return None


def _machine_model() -> str | None:
    """Modelo de máquina (DMI product_name o device-tree model en ARM)."""
    for path in (
        "/sys/devices/virtual/dmi/id/product_name",
        "/sys/firmware/devicetree/base/model",
        "/proc/device-tree/model",
    ):
        text = _read_first_line(path)
        if text:
            # device-tree a veces trae null bytes.
            cleaned = text.replace("\x00", "").strip()
            if cleaned and cleaned.lower() not in {"none", "to be filled by o.e.m.", "default string"}:
                return cleaned
    return None


def _facts_from_env() -> dict[str, Any] | None:
    """JSON de hechos del host inyectado por scripts/host-stats-report.sh."""
    injected = (os.environ.get("HOST_STATS_FACTS") or "").strip()
    if not injected:
        b64 = (os.environ.get("HOST_STATS_FACTS_B64") or "").strip()
        if b64:
            try:
                injected = base64.b64decode(b64).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                injected = ""
    if not injected:
        return None
    try:
        data = json.loads(injected)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _normalize_facts(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Normaliza campos de hechos del sistema (nulls si faltan / inválidos)."""
    src = raw if isinstance(raw, dict) else {}

    def _str(key: str) -> str | None:
        val = src.get(key)
        if val is None:
            return None
        text = str(val).strip()
        return text or None

    def _int(key: str) -> int | None:
        val = src.get(key)
        if val is None or val == "":
            return None
        try:
            return int(val)
        except (TypeError, ValueError):
            return None

    def _float(key: str) -> float | None:
        val = src.get(key)
        if val is None or val == "":
            return None
        try:
            return round(float(val), 1)
        except (TypeError, ValueError):
            return None

    return {
        "hostname": _str("hostname"),
        "cpu_model": _str("cpu_model"),
        "cpu_cores": _int("cpu_cores"),
        "cpu_arch": _str("cpu_arch"),
        "mem_total_bytes": _int("mem_total_bytes"),
        "disk_total_bytes": _int("disk_total_bytes"),
        "os_pretty_name": _str("os_pretty_name"),
        "kernel": _str("kernel"),
        "uptime_seconds": _float("uptime_seconds"),
        "machine_model": _str("machine_model"),
    }


def collect_host_facts() -> dict[str, Any]:
    """Características estáticas/semi-estáticas del sistema (CPU, RAM, OS, …).

    En contenedores Docker, ``scripts/host-stats-report.sh`` puede inyectar
    ``HOST_STATS_FACTS`` / ``HOST_STATS_FACTS_B64`` con hechos del host real
    (modelo, OS, kernel) porque el contenedor ve otra vista de /etc y a veces
    de /proc.
    """
    injected = _facts_from_env()
    if injected is not None:
        return _normalize_facts(injected)

    mem_total = None
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    num = line.split(":", 1)[1].strip().split()[0]
                    mem_total = int(num) * 1024
                    break
    except (OSError, IndexError, ValueError):
        pass

    disk_path = (
        (os.environ.get("HOST_STATS_DISK_PATH") or os.environ.get("CYBER_DAY_DISK_PATH") or "/").strip()
        or "/"
    )
    disk_total = None
    try:
        disk_total = int(shutil.disk_usage(disk_path).total)
    except OSError:
        pass

    kernel = None
    arch = None
    try:
        uname = os.uname()
        kernel = uname.release or None
        arch = uname.machine or None
    except AttributeError:
        pass

    return _normalize_facts(
        {
            "hostname": socket.gethostname() or None,
            "cpu_model": _cpu_model_from_proc(),
            "cpu_cores": os.cpu_count(),
            "cpu_arch": arch,
            "mem_total_bytes": mem_total,
            "disk_total_bytes": disk_total,
            "os_pretty_name": _os_pretty_name(),
            "kernel": kernel,
            "uptime_seconds": _uptime_seconds(),
            "machine_model": _machine_model(),
        }
    )


# Fuentes térmicas preferidas (menor índice = mejor). Tipos típicos de x86 / ARM / Orange Pi.
_THERMAL_TYPE_PRIORITY: dict[str, int] = {
    "x86_pkg_temp": 0,
    "k10temp": 1,
    "coretemp": 2,
    "cpu-thermal": 3,
    "cpu_thermal": 3,
    "soc-thermal": 4,
    "soc_thermal": 4,
    "cpu": 5,
    "package": 6,
    "acpitz": 20,
}


def _milli_celsius_to_c(raw: int) -> float | None:
    """Convierte lecturas sysfs (miligrados) a °C; rechaza valores absurdos."""
    # thermal_zone*/temp y hwmon temp*_input suelen estar en millidegrees.
    celsius = raw / 1000.0 if abs(raw) >= 200 else float(raw)
    if celsius < -20.0 or celsius > 150.0:
        return None
    return round(celsius, 1)


def _thermal_type_rank(type_name: str) -> int:
    key = (type_name or "").strip().lower()
    if key in _THERMAL_TYPE_PRIORITY:
        return _THERMAL_TYPE_PRIORITY[key]
    if "cpu" in key or "pkg" in key or "package" in key or "soc" in key:
        return 10
    if "gpu" in key or "nvme" in key or "wifi" in key:
        return 80
    return 50


def _read_thermal_zones() -> list[tuple[int, str, float]]:
    """Lista (rank, source, °C) desde /sys/class/thermal."""
    root = "/sys/class/thermal"
    rows: list[tuple[int, str, float]] = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return rows
    for name in names:
        if not name.startswith("thermal_zone"):
            continue
        base = os.path.join(root, name)
        try:
            with open(os.path.join(base, "type"), encoding="utf-8") as fh:
                type_name = fh.read().strip()
            with open(os.path.join(base, "temp"), encoding="utf-8") as fh:
                raw = int(fh.read().strip())
        except (OSError, ValueError):
            continue
        celsius = _milli_celsius_to_c(raw)
        if celsius is None:
            continue
        source = type_name or name
        rows.append((_thermal_type_rank(source), source, celsius))
    return rows


def _read_hwmon_temps() -> list[tuple[int, str, float]]:
    """Lista (rank, source, °C) desde /sys/class/hwmon (coretemp, k10temp, …)."""
    root = "/sys/class/hwmon"
    rows: list[tuple[int, str, float]] = []
    try:
        chips = sorted(os.listdir(root))
    except OSError:
        return rows
    for chip in chips:
        base = os.path.join(root, chip)
        try:
            with open(os.path.join(base, "name"), encoding="utf-8") as fh:
                chip_name = fh.read().strip() or chip
        except OSError:
            chip_name = chip
        try:
            entries = os.listdir(base)
        except OSError:
            continue
        for entry in sorted(entries):
            if not (entry.startswith("temp") and entry.endswith("_input")):
                continue
            label_path = os.path.join(base, entry.replace("_input", "_label"))
            label = ""
            try:
                with open(label_path, encoding="utf-8") as fh:
                    label = fh.read().strip()
            except OSError:
                pass
            try:
                with open(os.path.join(base, entry), encoding="utf-8") as fh:
                    raw = int(fh.read().strip())
            except (OSError, ValueError):
                continue
            celsius = _milli_celsius_to_c(raw)
            if celsius is None:
                continue
            source = f"{chip_name}:{label}" if label else chip_name
            rank = _thermal_type_rank(label or chip_name)
            # Preferir Package / Tctl sobre núcleos individuales.
            label_l = label.lower()
            if "package" in label_l or label_l in {"tctl", "tdie"}:
                rank = min(rank, 0)
            elif label_l.startswith("core"):
                rank = max(rank, 15)
            rows.append((rank, source, celsius))
    return rows


def collect_temperature() -> dict[str, Any] | None:
    """Temperatura del host (°C) desde env inyectado, thermal zones o hwmon.

    En contenedores Docker sin sysfs del host, el wrapper
    ``scripts/host-stats-report.sh`` puede inyectar ``HOST_STATS_TEMP_C``
    (y opcionalmente ``HOST_STATS_TEMP_SOURCE``).
    """
    injected = (os.environ.get("HOST_STATS_TEMP_C") or "").strip()
    if injected:
        try:
            celsius = round(float(injected), 1)
        except ValueError:
            celsius = None
        if celsius is not None and -20.0 <= celsius <= 150.0:
            source = (os.environ.get("HOST_STATS_TEMP_SOURCE") or "injected").strip() or "injected"
            return {"celsius": celsius, "source": source}

    candidates = _read_thermal_zones() + _read_hwmon_temps()
    if not candidates:
        return None
    candidates.sort(key=lambda row: (row[0], row[2]))
    _rank, source, celsius = candidates[0]
    return {"celsius": celsius, "source": source}


def collect_host_stats() -> dict[str, Any]:
    """Métricas del host donde corre el proceso (CPU / RAM / disco / temp / Docker)."""
    cores = os.cpu_count() or 1
    load1 = load5 = load15 = None
    try:
        load1, load5, load15 = os.getloadavg()
    except (AttributeError, OSError):
        pass
    cpu_pct = _cpu_percent_sample()
    if cpu_pct is None and load1 is not None and cores:
        cpu_pct = round(min(100.0, (float(load1) / float(cores)) * 100.0), 1)

    mem_total = mem_avail = None
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            info = {}
            for line in fh:
                if ":" not in line:
                    continue
                key, raw = line.split(":", 1)
                info[key] = raw.strip()

        def _kib(name: str) -> int | None:
            raw = info.get(name) or ""
            num = raw.split()[0] if raw else ""
            try:
                return int(num) * 1024
            except ValueError:
                return None

        mem_total = _kib("MemTotal")
        mem_avail = _kib("MemAvailable") or _kib("MemFree")
    except OSError:
        pass

    ram_used = ram_free = ram_pct = None
    if mem_total and mem_avail is not None:
        ram_used = max(0, mem_total - mem_avail)
        ram_free = mem_avail
        ram_pct = round((ram_used / mem_total) * 100.0, 1) if mem_total else None

    disk_path = (
        (os.environ.get("HOST_STATS_DISK_PATH") or os.environ.get("CYBER_DAY_DISK_PATH") or "/").strip()
        or "/"
    )
    disk_total = disk_used = disk_free = disk_pct = None
    try:
        usage = shutil.disk_usage(disk_path)
        disk_total = int(usage.total)
        disk_used = int(usage.used)
        disk_free = int(usage.free)
        disk_pct = round((disk_used / disk_total) * 100.0, 1) if disk_total else None
    except OSError:
        pass

    hostname = socket.gethostname()
    docker = collect_docker_df()
    temperature = collect_temperature()
    uptime = _uptime_seconds()
    facts = collect_host_facts()
    # Preferir hostname/uptime de facts inyectados (host real vs contenedor).
    if facts.get("hostname"):
        hostname = str(facts["hostname"])
    if facts.get("uptime_seconds") is not None:
        uptime = facts["uptime_seconds"]
    return {
        "hostname": hostname,
        "ip": _host_ip_guess(),
        "reported_at": _iso(_now()),
        "uptime_seconds": uptime,
        "cpu": {
            "percent": cpu_pct,
            "cores": cores,
            "load1": round(float(load1), 2) if load1 is not None else None,
            "load5": round(float(load5), 2) if load5 is not None else None,
            "load15": round(float(load15), 2) if load15 is not None else None,
        },
        "ram": {
            "used_bytes": ram_used,
            "free_bytes": ram_free,
            "total_bytes": mem_total,
            "percent": ram_pct,
        },
        "disk": {
            "path": disk_path,
            "used_bytes": disk_used,
            "free_bytes": disk_free,
            "total_bytes": disk_total,
            "percent": disk_pct,
        },
        "temperature": temperature,
        "docker": docker,
        "facts": facts,
    }


def host_alerts(host: dict[str, Any]) -> list[dict[str, str]]:
    """Alertas operativas para un host del panel admin."""
    alerts: list[dict[str, str]] = []
    if not host.get("online"):
        if host.get("reported_at"):
            alerts.append({"level": "warn", "code": "stale", "message": "Sin heartbeat reciente (stale)"})
        else:
            alerts.append({"level": "warn", "code": "no_data", "message": "Sin datos publicados"})
        return alerts

    disk = host.get("disk") or {}
    ram = host.get("ram") or {}
    temp = host.get("temperature") or {}
    docker = host.get("docker") or {}
    disk_pct = disk.get("percent")
    ram_pct = ram.get("percent")
    temp_c = temp.get("celsius") if isinstance(temp, dict) else None
    try:
        disk_n = float(disk_pct) if disk_pct is not None else None
    except (TypeError, ValueError):
        disk_n = None
    try:
        ram_n = float(ram_pct) if ram_pct is not None else None
    except (TypeError, ValueError):
        ram_n = None
    try:
        temp_n = float(temp_c) if temp_c is not None else None
    except (TypeError, ValueError):
        temp_n = None

    if disk_n is not None:
        free = disk.get("free_bytes")
        free_txt = ""
        if isinstance(free, (int, float)) and free >= 0:
            free_gib = free / (1024**3)
            free_txt = f" · libre {free_gib:.0f} GiB" if free_gib >= 10 else f" · libre {free_gib:.1f} GiB"
        if disk_n >= ALERT_DISK_HOT:
            alerts.append(
                {
                    "level": "hot",
                    "code": "disk_hot",
                    "message": f"Disco al {disk_n:.0f}%{free_txt}",
                }
            )
        elif disk_n >= ALERT_DISK_WARN:
            alerts.append(
                {
                    "level": "warn",
                    "code": "disk_warn",
                    "message": f"Disco al {disk_n:.0f}%{free_txt}",
                }
            )

    if ram_n is not None and ram_n >= ALERT_RAM_WARN:
        alerts.append(
            {
                "level": "warn",
                "code": "ram_warn",
                "message": f"RAM al {ram_n:.0f}%",
            }
        )

    if temp_n is not None:
        src = ""
        if isinstance(temp, dict) and temp.get("source"):
            src = f" ({temp['source']})"
        if temp_n >= ALERT_TEMP_HOT:
            alerts.append(
                {
                    "level": "hot",
                    "code": "temp_hot",
                    "message": f"Temperatura {temp_n:.0f}°C{src}",
                }
            )
        elif temp_n >= ALERT_TEMP_WARN:
            alerts.append(
                {
                    "level": "warn",
                    "code": "temp_warn",
                    "message": f"Temperatura {temp_n:.0f}°C{src}",
                }
            )

    reclaim = docker.get("reclaimable_bytes") if isinstance(docker, dict) else None
    if isinstance(reclaim, (int, float)) and reclaim >= ALERT_DOCKER_RECLAIM_GIB * (1000**3):
        gib = reclaim / (1000**3)
        alerts.append(
            {
                "level": "info",
                "code": "docker_reclaim",
                "message": f"Docker reclaimable ~{gib:.0f} GB (imágenes/volúmenes)",
            }
        )
    return alerts


def _alert_metric_price(code: str, host: dict[str, Any]) -> int:
    """Precio sintético para claim: menor = peor → reenvía si empeora dentro del cooldown."""
    if code in ("stale", "no_data"):
        return 100
    if code == "disk_hot":
        try:
            pct = float((host.get("disk") or {}).get("percent") or 90)
        except (TypeError, ValueError):
            pct = 90.0
        return max(1, int(round(10_000 - pct * 100)))
    if code == "temp_hot":
        try:
            temp = float((host.get("temperature") or {}).get("celsius") or 85)
        except (TypeError, ValueError):
            temp = 85.0
        return max(1, int(round(10_000 - temp * 100)))
    return 1000


def _alert_severity_score(code: str, host: dict[str, Any]) -> int:
    """Mayor = peor (para detectar empeoramiento frente al estado previo)."""
    if code in ("stale", "no_data"):
        return 1
    if code == "disk_hot":
        try:
            return max(1, int(round(float((host.get("disk") or {}).get("percent") or 90))))
        except (TypeError, ValueError):
            return 90
    if code == "temp_hot":
        try:
            return max(1, int(round(float((host.get("temperature") or {}).get("celsius") or 85))))
        except (TypeError, ValueError):
            return 85
    return 0


def _format_host_alert_text(host: dict[str, Any], alert: dict[str, Any]) -> str:
    label = str(host.get("label") or host.get("id") or "host")
    ip = str(host.get("ip") or "").strip()
    msg = str(alert.get("message") or alert.get("code") or "alerta")
    code = str(alert.get("code") or "")
    level = str(alert.get("level") or "warn").upper()
    where = f"{label} ({ip})" if ip else label
    lines = [
        f"Hosts · {level} · {where}",
        msg,
    ]
    if code:
        lines.append(f"código: {code}")
    role = str(host.get("role") or "").strip()
    if role:
        lines.append(role)
    return "\n".join(lines)


def _load_notify_state(repo: Any) -> dict[str, Any]:
    empty = {"active": {}, "notified": {}, "generations": {}}
    if not hasattr(repo, "get_app_setting"):
        return empty
    try:
        raw = repo.get_app_setting(HOST_ALERT_NOTIFY_STATE_KEY) or {}
    except Exception:
        return empty
    if not isinstance(raw, dict):
        return empty
    active = raw.get("active") if isinstance(raw.get("active"), dict) else {}
    notified = raw.get("notified") if isinstance(raw.get("notified"), dict) else {}
    generations = raw.get("generations") if isinstance(raw.get("generations"), dict) else {}
    return {
        "active": {str(k): int(v) for k, v in active.items() if str(k)},
        "notified": {str(k): int(v) for k, v in notified.items() if str(k)},
        "generations": {str(k): int(v) for k, v in generations.items() if str(k)},
    }


def _save_notify_state(repo: Any, state: dict[str, Any]) -> None:
    if not hasattr(repo, "save_app_setting"):
        return
    try:
        repo.save_app_setting(
            HOST_ALERT_NOTIFY_STATE_KEY,
            {
                "active": state.get("active") or {},
                "notified": state.get("notified") or {},
                "generations": state.get("generations") or {},
                "updated_at": _iso(_now()),
            },
        )
    except Exception:
        pass


def _send_host_alert_channels(text: str, *, entity_key: str, price: int, repo: Any) -> int:
    """Telegram chat admin (+ email ALERT_EMAIL_TO). Solo ops, no broadcast a usuarios."""
    delivered = 0
    try:
        from retail.batch.alerts import _secret, _telegram_text, send_email
    except Exception:
        return 0

    # Telegram: TELEGRAM_CHAT_ID / canales.local (destination_chats vía _telegram_text).
    claimed_tg = True
    if hasattr(repo, "claim_user_notification_send"):
        claimed_tg = repo.claim_user_notification_send(
            HOST_ALERT_NOTIFY_USER,
            "telegram",
            entity_key,
            price,
            cooldown_days=HOST_ALERT_NOTIFY_COOLDOWN_DAYS,
        )
    if claimed_tg:
        try:
            if _telegram_text(text):
                delivered += 1
            elif hasattr(repo, "release_user_notification_send"):
                repo.release_user_notification_send(
                    HOST_ALERT_NOTIFY_USER, "telegram", entity_key, price
                )
        except Exception as exc:
            print(f"host-stats: telegram alerta: {exc}", flush=True)
            if hasattr(repo, "release_user_notification_send"):
                try:
                    repo.release_user_notification_send(
                        HOST_ALERT_NOTIFY_USER, "telegram", entity_key, price
                    )
                except Exception:
                    pass

    to_addr = _secret("ALERT_EMAIL_TO", "alert_email_to").strip()
    if to_addr and _secret("SMTP_HOST", "smtp_host").strip():
        claimed_em = True
        if hasattr(repo, "claim_user_notification_send"):
            claimed_em = repo.claim_user_notification_send(
                HOST_ALERT_NOTIFY_USER,
                "email",
                entity_key,
                price,
                cooldown_days=HOST_ALERT_NOTIFY_COOLDOWN_DAYS,
            )
        if claimed_em:
            subject = text.split("\n", 1)[0][:120] or "Hosts · alerta"
            try:
                if send_email(to_addr, subject, text):
                    delivered += 1
                elif hasattr(repo, "release_user_notification_send"):
                    repo.release_user_notification_send(
                        HOST_ALERT_NOTIFY_USER, "email", entity_key, price
                    )
            except Exception as exc:
                print(f"host-stats: email alerta: {exc}", flush=True)
                if hasattr(repo, "release_user_notification_send"):
                    try:
                        repo.release_user_notification_send(
                            HOST_ALERT_NOTIFY_USER, "email", entity_key, price
                        )
                    except Exception:
                        pass
    return delivered


def notify_host_alerts(repo: Any, *, payload: dict[str, Any] | None = None) -> int:
    """Notifica admins si hay alertas nuevas/peores (stale, disco crítico, temp hot).

    Canales: Telegram admin (TELEGRAM_CHAT_ID / canales) y opcionalmente
    ALERT_EMAIL_TO. No envía a usuarios finales.

    Dedupe: estado en app_settings (generación por episodio) +
    claim_user_notification_send por host+código (cooldown
    HOST_STATS_ALERT_COOLDOWN_DAYS, default 1 día; reenvía si empeora).
    """
    data = payload if isinstance(payload, dict) else admin_hosts_payload(repo)
    state = _load_notify_state(repo)
    prev_active: dict[str, int] = dict(state.get("active") or {})
    notified: dict[str, int] = dict(state.get("notified") or {})
    generations: dict[str, int] = dict(state.get("generations") or {})

    current_active: dict[str, int] = {}
    pending: list[tuple[dict[str, Any], dict[str, Any], str, int]] = []

    for host in data.get("hosts") or []:
        if not isinstance(host, dict):
            continue
        host_id = str(host.get("id") or "").strip()
        if not host_id:
            continue
        for alert in host.get("alerts") or []:
            if not isinstance(alert, dict):
                continue
            code = str(alert.get("code") or "").strip()
            if code not in HOST_NOTIFY_ALERT_CODES:
                continue
            key = f"{host_id}:{code}"
            score = _alert_severity_score(code, host)
            current_active[key] = score
            last_notified = notified.get(key)
            # Nuevo episodio, o empeoró respecto a lo ya avisado.
            if last_notified is None or score > last_notified:
                pending.append((host, alert, key, score))

    # Alertas que desaparecieron: subir generación para poder reavisar si vuelven.
    for key in list(prev_active):
        if key not in current_active:
            generations[key] = int(generations.get(key) or 0) + 1
            notified.pop(key, None)

    delivered = 0
    for host, alert, key, score in pending:
        code = str(alert.get("code") or "")
        gen = int(generations.get(key) or 0)
        entity_key = f"host:{key}:g{gen}"
        price = _alert_metric_price(code, host)
        text = _format_host_alert_text(host, alert)
        sent = _send_host_alert_channels(
            text, entity_key=entity_key, price=price, repo=repo
        )
        delivered += sent
        if sent:
            notified[key] = score

    _save_notify_state(
        repo,
        {
            "active": current_active,
            "notified": notified,
            "generations": generations,
        },
    )
    return delivered


def _host_stats_key(stats: dict[str, Any]) -> str:
    """Clave estable: IP del host (varios contenedores Docker → un solo panel)."""
    ip = str(stats.get("ip") or HOST_IP or CYBER_DAY_HOST_IP or "").strip()
    if ip:
        return ip
    return str(stats.get("hostname") or "unknown").strip() or "unknown"


def _history_point(stats: dict[str, Any]) -> dict[str, Any]:
    """Punto compacto para la serie histórica (mismo doc Mongo)."""
    cpu = stats.get("cpu") if isinstance(stats.get("cpu"), dict) else {}
    ram = stats.get("ram") if isinstance(stats.get("ram"), dict) else {}
    disk = stats.get("disk") if isinstance(stats.get("disk"), dict) else {}
    temp = stats.get("temperature") if isinstance(stats.get("temperature"), dict) else {}
    docker = stats.get("docker") if isinstance(stats.get("docker"), dict) else {}
    return {
        "t": stats.get("reported_at"),
        "cpu": cpu.get("percent"),
        "ram": ram.get("percent"),
        "disk": disk.get("percent"),
        "temp": temp.get("celsius"),
        "dkr": docker.get("reclaimable_bytes"),
    }


def _parse_history_ts(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def merge_host_history(
    previous: dict[str, Any] | None,
    stats: dict[str, Any],
    *,
    max_points: int | None = None,
    max_age_seconds: int | None = None,
) -> list[dict[str, Any]]:
    """Append del snapshot actual + retención acotada (edad y cantidad)."""
    cap = max_points if max_points is not None else HOST_STATS_HISTORY_MAX
    max_age = max_age_seconds if max_age_seconds is not None else HOST_STATS_HISTORY_MAX_AGE
    prev_rows = []
    if isinstance(previous, dict):
        raw = previous.get("history")
        if isinstance(raw, list):
            prev_rows = [row for row in raw if isinstance(row, dict)]

    point = _history_point(stats)
    point_ts = _parse_history_ts(point.get("t"))
    cutoff = None
    if point_ts is not None and max_age > 0:
        cutoff = point_ts.timestamp() - float(max_age)

    merged: list[dict[str, Any]] = []
    seen_t = set()
    point_t = point.get("t")
    if point_t:
        seen_t.add(str(point_t))
    for row in prev_rows:
        ts = _parse_history_ts(row.get("t"))
        if cutoff is not None and ts is not None and ts.timestamp() < cutoff:
            continue
        row_t = _iso(row.get("t")) if isinstance(row.get("t"), datetime) else row.get("t")
        # Evitar duplicar el mismo instante exacto (re-save del mismo snapshot).
        if row_t is not None and str(row_t) in seen_t:
            continue
        if row_t is not None:
            seen_t.add(str(row_t))
        merged.append(
            {
                "t": row_t,
                "cpu": row.get("cpu"),
                "ram": row.get("ram"),
                "disk": row.get("disk"),
                "temp": row.get("temp"),
                "dkr": row.get("dkr"),
            }
        )
    merged.append(point)
    if cap > 0 and len(merged) > cap:
        merged = merged[-cap:]
    return merged


def report_host_stats(repo: Any, *, force: bool = False) -> dict[str, Any] | None:
    """Persiste métricas del host (1 doc por máquina) + historial acotado."""
    global _LAST_HOST_REPORT_AT
    now = time.monotonic()
    if not force and (now - _LAST_HOST_REPORT_AT) < HOST_STATS_REPORT_SECONDS:
        return None
    _LAST_HOST_REPORT_AT = now
    stats = collect_host_stats()
    key = f"{HOST_STATS_SETTING_PREFIX}{_host_stats_key(stats)}"
    previous = None
    if hasattr(repo, "get_app_setting"):
        try:
            previous = repo.get_app_setting(key)
        except Exception:
            previous = None
    stats["history"] = merge_host_history(previous, stats)
    if hasattr(repo, "save_app_setting"):
        repo.save_app_setting(key, stats)
    # Tras guardar: revisar los 3 hosts (stale de otros, disco/temp de este).
    try:
        notify_host_alerts(repo)
    except Exception as exc:
        print(f"host-stats: notify alerts: {exc}", flush=True)
    return stats


def _reported_age_seconds(reported: Any) -> float | None:
    if isinstance(reported, datetime):
        hb = reported if reported.tzinfo else reported.replace(tzinfo=timezone.utc)
        return (_now() - hb).total_seconds()
    if isinstance(reported, str) and reported:
        try:
            hb = datetime.fromisoformat(reported.replace("Z", "+00:00"))
            return (_now() - hb).total_seconds()
        except ValueError:
            return None
    return None


def display_label(stats: dict[str, Any] | None) -> str:
    """Etiqueta clara para UI (BMAX / soyo / Orange Pi)."""
    if not stats:
        return "—"
    ip = str(stats.get("ip") or "").strip()
    for known in KNOWN_HOSTS:
        if known["ip"] == ip:
            return known["label"]
    hostname = str(stats.get("hostname") or "").strip()
    host_l = hostname.lower()
    if "precios-cyber-pi" in host_l or "orangepi" in host_l or host_l in {"orange-pi", "orangepi5", "opi"}:
        return "Orange Pi"
    if host_l in {"bmax", "precios-web", "precios"} or "bmax" in host_l:
        return "BMAX"
    if host_l in {"soyo", "precios-worker-soyo"} or host_l.startswith("soyo"):
        return "soyo"
    return hostname or ip or "unknown"


def _raw_host_docs(repo: Any) -> list[dict[str, Any]]:
    by_key: dict[str, dict[str, Any]] = {}
    coll = getattr(repo, "app_settings", None)
    if coll is None:
        return []
    try:
        cursor = coll.find({"_id": {"$regex": f"^{re.escape(HOST_STATS_SETTING_PREFIX)}"}})
        docs = list(cursor)
    except Exception:
        return []
    for doc in docs:
        payload = {k: v for k, v in doc.items() if k != "_id"}
        key = _host_stats_key(payload)
        if not key:
            continue
        prev = by_key.get(key)
        if prev is None or str(payload.get("reported_at") or "") >= str(prev.get("reported_at") or ""):
            by_key[key] = payload
    return list(by_key.values())


def load_host_stats(repo: Any) -> list[dict[str, Any]]:
    """Hosts con métricas recientes (Cyber), dedupe por IP; añade `label`."""
    fresh: list[dict[str, Any]] = []
    for payload in _raw_host_docs(repo):
        age = _reported_age_seconds(payload.get("reported_at"))
        age_ok = age is None or age <= HOST_STATS_MAX_AGE
        if not age_ok:
            continue
        view = dict(payload)
        reported = payload.get("reported_at")
        view["reported_at"] = _iso(reported) if isinstance(reported, datetime) else reported
        view["label"] = display_label(view)
        view["stale"] = False
        fresh.append(view)
    lan = [h for h in fresh if str(h.get("ip") or "").startswith("192.168.")]
    rows = lan if lan else fresh
    return sorted(rows, key=lambda h: str(h.get("ip") or h.get("hostname") or ""))


def admin_hosts_payload(repo: Any) -> dict[str, Any]:
    """Lista fija BMAX / soyo / Orange Pi con métricas, alertas y flag stale."""
    by_ip: dict[str, dict[str, Any]] = {}
    for payload in _raw_host_docs(repo):
        ip = str(payload.get("ip") or "").strip()
        if not ip:
            ip = _host_stats_key(payload)
        by_ip[ip] = payload

    hosts: list[dict[str, Any]] = []
    for known in KNOWN_HOSTS:
        raw = by_ip.get(known["ip"])
        if raw is None:
            row = {
                "id": known["id"],
                "label": known["label"],
                "role": known.get("role"),
                "ssh": known.get("ssh"),
                "image": known.get("image"),
                "ip": known["ip"],
                "hostname": None,
                "reported_at": None,
                "stale": True,
                "online": False,
                "uptime_seconds": None,
                "cpu": None,
                "ram": None,
                "disk": None,
                "temperature": None,
                "docker": None,
                "facts": None,
                "history": [],
            }
            row["alerts"] = host_alerts(row)
            hosts.append(row)
            continue
        age = _reported_age_seconds(raw.get("reported_at"))
        stale = age is None or age > HOST_STATS_MAX_AGE
        reported = raw.get("reported_at")
        history_raw = raw.get("history")
        history = [h for h in history_raw if isinstance(h, dict)] if isinstance(history_raw, list) else []
        row = {
            "id": known["id"],
            "label": known["label"],
            "role": known.get("role"),
            "ssh": known.get("ssh"),
            "image": known.get("image"),
            "ip": known["ip"],
            "hostname": raw.get("hostname"),
            "reported_at": _iso(reported) if isinstance(reported, datetime) else reported,
            "stale": stale,
            "online": not stale,
            "age_seconds": round(age, 1) if age is not None else None,
            "uptime_seconds": raw.get("uptime_seconds"),
            "cpu": raw.get("cpu"),
            "ram": raw.get("ram"),
            "disk": raw.get("disk"),
            "temperature": raw.get("temperature"),
            "docker": raw.get("docker"),
            "facts": raw.get("facts") if isinstance(raw.get("facts"), dict) else None,
            "history": history,
        }
        row["alerts"] = host_alerts(row)
        hosts.append(row)

    severity = {"hot": 3, "warn": 2, "info": 1}
    alert_banner = []
    for host in hosts:
        for alert in host.get("alerts") or []:
            alert_banner.append(
                {
                    "host_id": host["id"],
                    "label": host["label"],
                    "level": alert.get("level") or "info",
                    "code": alert.get("code"),
                    "message": alert.get("message"),
                }
            )
    alert_banner.sort(key=lambda a: (-severity.get(str(a.get("level")), 0), str(a.get("label"))))

    return {
        "ok": True,
        "hosts": hosts,
        "alerts": alert_banner,
        "thresholds": {
            "disk_warn": ALERT_DISK_WARN,
            "disk_hot": ALERT_DISK_HOT,
            "ram_warn": ALERT_RAM_WARN,
            "temp_warn": ALERT_TEMP_WARN,
            "temp_hot": ALERT_TEMP_HOT,
            "docker_reclaim_gib": ALERT_DOCKER_RECLAIM_GIB,
            "stale_seconds": HOST_STATS_MAX_AGE,
        },
        "history": {
            "max_points": HOST_STATS_HISTORY_MAX,
            "max_age_seconds": HOST_STATS_HISTORY_MAX_AGE,
        },
        "max_age_seconds": HOST_STATS_MAX_AGE,
        "report_interval_seconds": HOST_STATS_REPORT_SECONDS,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Reporta CPU/RAM/disco/temp del host a Mongo.")
    parser.add_argument("--once", action="store_true", help="Una sola publicación (default)")
    parser.add_argument("--loop", action="store_true", help="Publicar en bucle")
    parser.add_argument(
        "--check-alerts",
        action="store_true",
        help="Solo evaluar alertas y notificar admins (sin reportar métricas)",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=HOST_STATS_REPORT_SECONDS,
        help="Segundos entre reportes en --loop",
    )
    args = parser.parse_args()
    from retail.mongo import ProductRepository

    repo = ProductRepository()
    try:
        if args.check_alerts:
            sent = notify_host_alerts(repo)
            print(f"host-stats: check-alerts enviados={sent}", flush=True)
            return
        if args.loop:
            interval = max(5.0, float(args.interval))
            print(f"host-stats: loop cada {interval}s → Mongo", flush=True)
            while True:
                try:
                    stats = report_host_stats(repo, force=True)
                    if stats:
                        temp = (stats.get("temperature") or {}).get("celsius")
                        temp_txt = f" temp={temp}°C" if temp is not None else ""
                        print(
                            f"host-stats: {display_label(stats)} "
                            f"{stats.get('ip')} cpu={stats.get('cpu', {}).get('percent')}%"
                            f"{temp_txt}",
                            flush=True,
                        )
                except Exception as exc:
                    print(f"host-stats: error: {exc}", flush=True)
                time.sleep(interval)
        else:
            stats = report_host_stats(repo, force=True)
            if stats:
                print(
                    f"host-stats: ok {display_label(stats)} ip={stats.get('ip')} "
                    f"host={stats.get('hostname')}",
                    flush=True,
                )
            else:
                raise SystemExit("host-stats: no se pudo reportar")
    finally:
        repo.close()


if __name__ == "__main__":
    main()
