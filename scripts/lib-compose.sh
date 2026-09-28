#!/usr/bin/env bash
# Helpers compose — preferir v2; workaround v1 ContainerConfig
# shellcheck disable=SC2034

detect_compose() {
  if docker compose version >/dev/null 2>&1; then
    echo "docker compose"
    return 0
  fi
  if command -v sudo >/dev/null 2>&1 && sudo docker compose version >/dev/null 2>&1; then
    echo "sudo docker compose"
    return 0
  fi
  if command -v docker-compose >/dev/null 2>&1; then
    echo "docker-compose"
    return 0
  fi
  return 1
}

# compose_up_safe "docker compose|-f a.yml|-f b.yml" container1 container2
# Primer arg: comando compose + flags unidos con |  (evita word-split de "docker compose")
# Resto: nombres de contenedor a rm en workaround v1
compose_up_safe() {
  local spec="$1"; shift
  local rms=("$@")
  local -a cmd=()
  IFS='|' read -r -a cmd <<<"$spec"

  case "${cmd[0]}" in
    docker-compose)
      echo "==> Workaround docker-compose v1: down + rm + up"
      "${cmd[@]}" down || true
      local c
      for c in "${rms[@]}"; do
        [[ -n "$c" ]] && docker rm -f "$c" 2>/dev/null || true
      done
      "${cmd[@]}" up -d
      ;;
    *)
      "${cmd[@]}" up -d --remove-orphans
      ;;
  esac
}
