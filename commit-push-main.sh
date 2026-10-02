#!/usr/bin/env bash
# Commitea cambios locales y pushea a origin/main.
# Uso: ./commit-push-main.sh ["mensaje del commit"]
# Rama local suele ser master; destino remoto: main (sin force).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "ERROR: no es un repositorio git: $ROOT" >&2
  exit 1
fi

GIT_ROOT="$(git rev-parse --show-toplevel)"
cd "$GIT_ROOT"

info() { echo "==> $*"; }
warn() { echo "[!] $*"; }

info "git status"
git status -sb
echo

# ¿Hay cambios locales (tracked/untracked) o commits por empujar?
dirty=false
if [[ -n "$(git status --porcelain)" ]]; then
  dirty=true
fi

ahead=0
if git rev-parse --abbrev-ref '@{u}' >/dev/null 2>&1; then
  ahead="$(git rev-list --count '@{u}..HEAD' 2>/dev/null || echo 0)"
else
  # Sin upstream: si hay commits locales, conviene empujar.
  ahead="$(git rev-list --count 'origin/main..HEAD' 2>/dev/null || echo 1)"
fi

if [[ "$dirty" != true && "$ahead" -eq 0 ]]; then
  info "Nada que hacer: working tree limpio y al día con el remoto."
  exit 0
fi

if [[ "$dirty" == true ]]; then
  # Evitar stagear secretos obvios; el resto con git add -A respetando .gitignore.
  secret_hits=()
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    # status porcelain: XY PATH  o  XY ORIG -> PATH
    path="${line:3}"
    path="${path##* -> }"
    base="$(basename "$path")"
    case "$path" in
      .env|.env.*|*.pem|*.key|*credentials*|*/credentials*|id_rsa*|*.p12|*.pfx)
        # Permitir ejemplos públicos
        case "$base" in
          *.example|*.sample|*.template) continue ;;
        esac
        secret_hits+=("$path")
        ;;
    esac
  done < <(git status --porcelain)

  if ((${#secret_hits[@]} > 0)); then
    warn "Omitiendo posibles secretos (no se stagean):"
    for p in "${secret_hits[@]}"; do
      echo "    - $p"
    done
  fi

  info "Staging (git add -A)"
  git add -A

  # Des-stagear secretos si quedaron en el index
  for p in "${secret_hits[@]+"${secret_hits[@]}"}"; do
    git reset -q -- "$p" 2>/dev/null || true
  done

  if [[ -z "$(git status --porcelain)" ]]; then
    if [[ "$ahead" -eq 0 ]]; then
      info "Nada que commitear (solo había secretos omitidos) y no hay commits pendientes de push."
      exit 0
    fi
    warn "Sin cambios stageables; se intentará push de commits ya existentes."
  elif [[ -z "$(git diff --cached --name-only)" ]]; then
    if [[ "$ahead" -eq 0 ]]; then
      info "Nada stageado (¿solo secretos?) y no hay commits por empujar."
      exit 0
    fi
    warn "Nada stageado; se intentará push de commits ya existentes."
  else
    if [[ $# -gt 0 ]]; then
      msg="$*"
    elif [[ -t 0 ]]; then
      default_msg="chore: sync $(date '+%Y-%m-%d %H:%M')"
      read -r -p "Mensaje del commit [${default_msg}]: " msg || true
      msg="${msg:-$default_msg}"
    else
      msg="chore: sync $(date '+%Y-%m-%d %H:%M')"
      info "Sin TTY; usando mensaje por defecto: $msg"
    fi

    info "Commit: $msg"
    git commit -m "$msg"
  fi
fi

branch="$(git rev-parse --abbrev-ref HEAD)"
info "Push $branch → origin/main (sin force)"
# Sin -u: no reescribe git config / upstream (ya suele ser origin/main).
git push origin HEAD:main

info "OK"
git status -sb
