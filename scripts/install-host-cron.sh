#!/usr/bin/env bash
# Instala el cron del batch en el HOST (BMAX), no dentro del contenedor.
# Una línea por grupo de tiendas, escalonada según programacion.json.
#
# HOST_BATCH_CRON=0 en .env (o entorno): no instala ofertas-diarias-bmax.sh
# (el scrape programado vive en soyo). Sí puede dejar solo alertas predictivas
# (run_on_bmax.sh) si programacion.json sigue enabled=true.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
chmod +x "${ROOT}/scripts/ofertas-diarias-bmax.sh"
chmod +x "${ROOT}/scripts/run_on_bmax.sh"

if [[ -z "${HOST_BATCH_CRON:-}" && -f "${ROOT}/.env" ]]; then
  _hb="$(grep -E '^HOST_BATCH_CRON=' "${ROOT}/.env" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '\r' || true)"
  [[ -n "${_hb}" ]] && HOST_BATCH_CRON="${_hb}"
  unset _hb
fi
HOST_BATCH_CRON="${HOST_BATCH_CRON:-1}"

BEGIN="# retail-ofertas-begin"
END="# retail-ofertas-end"
SCRIPT="${ROOT}/scripts/ofertas-diarias-bmax.sh"

info() { echo "[✓] $*"; }
warn() { echo "[!] $*"; }

if ! command -v crontab >/dev/null 2>&1; then
  echo "[✗] En el host no hay crontab. Instala cron (p. ej. sudo apt-get install -y cron) y reintenta." >&2
  exit 1
fi

mkdir -p "${ROOT}/logs" "${ROOT}/output"

current=""
if current="$(crontab -l 2>/dev/null)"; then
  :
else
  current=""
fi

cleaned="$(printf '%s\n' "$current" | python3 -c '
import sys
begin, end = sys.argv[1], sys.argv[2]
text = sys.stdin.read()
kept = []
skip = False
for line in text.splitlines():
    if line.strip() == begin:
        skip = True
        continue
    if line.strip() == end:
        skip = False
        continue
    if not skip:
        kept.append(line)
print("\n".join(kept).rstrip())
' "$BEGIN" "$END")"

block=""
if block="$(HOST_BATCH_CRON="${HOST_BATCH_CRON}" python3 <<'PY'
import json
import os
from pathlib import Path

path = Path("retail/batch/programacion.json")
data = json.loads(path.read_text()) if path.exists() else {}
if not data.get("enabled"):
    raise SystemExit(0)

host_batch = (os.environ.get("HOST_BATCH_CRON") or "1").strip().lower()
install_batch = host_batch not in {"0", "false", "no", "off"}

hour = int(6 if data.get("hour") is None else data["hour"])
minute = int(0 if data.get("minute") is None else data["minute"])
groups_cfg = data.get("groups") if isinstance(data.get("groups"), dict) else {}
mode = groups_cfg.get("mode") or "per_group"
stagger = max(5, min(180, int(groups_cfg.get("stagger_minutes") or 45)))
selected = groups_cfg.get("enabled")

try:
    from retail.batch.config import load_schedule
    from retail.store_categories import enabled_group_ids
    groups = enabled_group_ids(load_schedule())
except Exception:
    from retail.registry import GROUP_ORDER
    groups = list(GROUP_ORDER)
    if selected is not None:
        wanted = {str(x).strip().lower() for x in selected if str(x).strip()}
        groups = [g for g in groups if g in wanted]

root = Path(".").resolve()
script = root / "scripts" / "ofertas-diarias-bmax.sh"
predictive_script = root / "scripts" / "run_on_bmax.sh"
begin = "# retail-ofertas-begin"
end = "# retail-ofertas-end"
lines = [begin, "CRON_TZ=America/Santiago"]
if install_batch:
    if mode == "single":
        log = root / "logs" / "ofertas-diarias.log"
        lines.append(f"{minute} {hour} * * * {script} >> {log} 2>&1")
    else:
        total = hour * 60 + minute
        for grupo in groups:
            h, m = (total // 60) % 24, total % 60
            log = root / "logs" / f"ofertas-diarias-{grupo}.log"
            lines.append(f"{m} {h} * * * {script} {grupo} >> {log} 2>&1")
            total += stagger
else:
    lines.append("# HOST_BATCH_CRON=0 — ofertas en soyo; solo predictive en BMAX")

# Se ejecuta después de los lotes para validar TimesFM, generar pronósticos y
# evaluar las suscripciones. El propio proceso impide los envíos mientras la
# validación no alcance los mínimos de precisión.
predictive_hour = max(0, min(23, int(data.get("predictive_hour") or 21)))
predictive_minute = max(0, min(59, int(data.get("predictive_minute") or 30)))
predictive_log = root / "logs" / "alertas-predictivas.log"
lines.append(
    f"{predictive_minute} {predictive_hour} * * * {predictive_script} "
    f">> {predictive_log} 2>&1"
)
lines.append(end)
print("\n".join(lines))
PY
)"; then
  if [[ "${HOST_BATCH_CRON}" =~ ^(0|false|no|off)$ ]]; then
    info "HOST_BATCH_CRON=0 → sin ofertas-diarias-bmax; solo predictive en BMAX"
  else
    info "Cron por grupo America/Santiago → ${SCRIPT} <grupo>"
  fi
else
  block=""
  warn "programacion.json enabled=false; se quita la línea del crontab"
fi

{
  [[ -n "$cleaned" ]] && printf '%s\n' "$cleaned"
  [[ -n "$block" ]] && printf '%s\n' "$block"
} | crontab -

if [[ -n "$block" ]]; then
  info "crontab instalado"
  crontab -l | sed -n "/${BEGIN}/,/${END}/p" || true
else
  info "crontab de precios removido"
fi
