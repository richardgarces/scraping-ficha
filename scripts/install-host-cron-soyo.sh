#!/usr/bin/env bash
# Instala el cron del batch en soyo (venv + ofertas-diarias-soyo.sh).
# No instala run_on_bmax.sh (alertas predictivas / TimesFM: quedan en BMAX).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
chmod +x "${ROOT}/scripts/ofertas-diarias-soyo.sh"

BEGIN="# retail-ofertas-begin"
END="# retail-ofertas-end"
SCRIPT="${ROOT}/scripts/ofertas-diarias-soyo.sh"

info() { echo "[✓] $*"; }
warn() { echo "[!] $*"; }

if ! command -v crontab >/dev/null 2>&1; then
  echo "[✗] En el host no hay crontab. Instala cron y reintenta." >&2
  exit 1
fi

if [[ ! -f "${ROOT}/.venv/bin/activate" && ! -x "${ROOT}/.venv/bin/retail" ]]; then
  if docker image inspect precios-worker >/dev/null 2>&1; then
    info "Sin .venv; ofertas-diarias-soyo.sh usará imagen Docker precios-worker"
  else
    warn "No hay .venv ni imagen precios-worker; el cron fallará hasta crear uno de los dos."
  fi
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
if block="$(python3 <<'PY'
import json
from pathlib import Path

path = Path("retail/batch/programacion.json")
data = json.loads(path.read_text()) if path.exists() else {}
if not data.get("enabled"):
    raise SystemExit(0)

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
script = root / "scripts" / "ofertas-diarias-soyo.sh"
begin = "# retail-ofertas-begin"
end = "# retail-ofertas-end"
lines = [begin, "CRON_TZ=America/Santiago"]
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

# Predictive/TimesFM NO va en soyo — solo en BMAX (run_on_bmax.sh).
lines.append(end)
print("\n".join(lines))
PY
)"; then
  info "Cron soyo por grupo America/Santiago → ${SCRIPT} <grupo>"
else
  block=""
  warn "programacion.json enabled=false; se quita el bloque del crontab"
fi

{
  [[ -n "$cleaned" ]] && printf '%s\n' "$cleaned"
  [[ -n "$block" ]] && printf '%s\n' "$block"
} | crontab -

if [[ -n "$block" ]]; then
  info "crontab soyo instalado (sin predictive)"
  crontab -l | sed -n "/${BEGIN}/,/${END}/p" || true
else
  info "crontab de ofertas removido en soyo"
fi
