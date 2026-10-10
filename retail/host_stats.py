"""Métricas de host (CPU / RAM / disco) → Mongo `cyber_day_host_stats:{ip}`.

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
ALERT_DISK_WARN = max(50, int(os.environ.get("HOST_STATS_DISK_WARN") or "80"))
ALERT_DISK_HOT = max(ALERT_DISK_WARN, int(os.environ.get("HOST_STATS_DISK_HOT") or "90"))
ALERT_RAM_WARN = max(50, int(os.environ.get("HOST_STATS_RAM_WARN") or "90"))
# Docker reclaimable ≥ este umbral (GiB) → alerta informativa.
ALERT_DOCKER_RECLAIM_GIB = max(1.0, float(os.environ.get("HOST_STATS_DOCKER_RECLAIM_GIB") or "20"))
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


def collect_host_stats() -> dict[str, Any]:
    """Métricas del host donde corre el proceso (CPU / RAM / disco / Docker)."""
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
    uptime = _uptime_seconds()
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
        "docker": docker,
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
    docker = host.get("docker") or {}
    disk_pct = disk.get("percent")
    ram_pct = ram.get("percent")
    try:
        disk_n = float(disk_pct) if disk_pct is not None else None
    except (TypeError, ValueError):
        disk_n = None
    try:
        ram_n = float(ram_pct) if ram_pct is not None else None
    except (TypeError, ValueError):
        ram_n = None

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


def _host_stats_key(stats: dict[str, Any]) -> str:
    """Clave estable: IP del host (varios contenedores Docker → un solo panel)."""
    ip = str(stats.get("ip") or HOST_IP or CYBER_DAY_HOST_IP or "").strip()
    if ip:
        return ip
    return str(stats.get("hostname") or "unknown").strip() or "unknown"


def report_host_stats(repo: Any, *, force: bool = False) -> dict[str, Any] | None:
    """Persiste métricas del host (1 doc por máquina)."""
    global _LAST_HOST_REPORT_AT
    now = time.monotonic()
    if not force and (now - _LAST_HOST_REPORT_AT) < HOST_STATS_REPORT_SECONDS:
        return None
    _LAST_HOST_REPORT_AT = now
    stats = collect_host_stats()
    key = f"{HOST_STATS_SETTING_PREFIX}{_host_stats_key(stats)}"
    if hasattr(repo, "save_app_setting"):
        repo.save_app_setting(key, stats)
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
                "docker": None,
            }
            row["alerts"] = host_alerts(row)
            hosts.append(row)
            continue
        age = _reported_age_seconds(raw.get("reported_at"))
        stale = age is None or age > HOST_STATS_MAX_AGE
        reported = raw.get("reported_at")
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
            "docker": raw.get("docker"),
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
            "docker_reclaim_gib": ALERT_DOCKER_RECLAIM_GIB,
            "stale_seconds": HOST_STATS_MAX_AGE,
        },
        "max_age_seconds": HOST_STATS_MAX_AGE,
        "report_interval_seconds": HOST_STATS_REPORT_SECONDS,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Reporta CPU/RAM/disco del host a Mongo.")
    parser.add_argument("--once", action="store_true", help="Una sola publicación (default)")
    parser.add_argument("--loop", action="store_true", help="Publicar en bucle")
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
        if args.loop:
            interval = max(5.0, float(args.interval))
            print(f"host-stats: loop cada {interval}s → Mongo", flush=True)
            while True:
                try:
                    stats = report_host_stats(repo, force=True)
                    if stats:
                        print(
                            f"host-stats: {display_label(stats)} "
                            f"{stats.get('ip')} cpu={stats.get('cpu', {}).get('percent')}%",
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
