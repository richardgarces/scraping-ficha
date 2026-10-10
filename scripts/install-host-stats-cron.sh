#!/usr/bin/env bash
# Instala cron cada minuto: scripts/host-stats-report.sh (BMAX o soyo).
# Uso:
#   HOST_STATS_HOST_IP=192.168.1.198 bash scripts/install-host-stats-cron.sh
#   HOST_STATS_HOST_IP=192.168.1.197 bash scripts/install-host-stats-cron.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
chmod +x "${ROOT}/scripts/host-stats-report.sh"

BEGIN="# retail-host-stats-begin"
END="# retail-host-stats-end"
SCRIPT="${ROOT}/scripts/host-stats-report.sh"
LOG="${ROOT}/logs/host-stats-cron.log"

info() { echo "[✓] $*"; }
warn() { echo "[!] $*"; }

if ! command -v crontab >/dev/null 2>&1; then
  echo "[✗] En el host no hay crontab." >&2
  exit 1
fi

mkdir -p "${ROOT}/logs"

# Inferir IP si falta
if [[ -z "${HOST_STATS_HOST_IP:-}" ]]; then
  case "$(hostname -s 2>/dev/null || hostname || true)" in
    soyo*) HOST_STATS_HOST_IP=192.168.1.197 ;;
    *) HOST_STATS_HOST_IP=192.168.1.198 ;;
  esac
fi

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

block="$(cat <<EOF
${BEGIN}
CRON_TZ=America/Santiago
* * * * * HOST_STATS_HOST_IP=${HOST_STATS_HOST_IP} CYBER_DAY_HOST_IP=${HOST_STATS_HOST_IP} ${SCRIPT} >>${LOG} 2>&1
${END}
EOF
)"

{
  printf '%s\n' "$cleaned"
  [[ -n "$cleaned" ]] && printf '\n'
  printf '%s\n' "$block"
} | crontab -

info "Cron host-stats instalado (IP=${HOST_STATS_HOST_IP})"
info "Probar: HOST_STATS_HOST_IP=${HOST_STATS_HOST_IP} ${SCRIPT}"
crontab -l | sed -n "/${BEGIN}/,/${END}/p"
