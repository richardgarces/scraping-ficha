# Monitoreo: BMAX Prometheus ↔ soyo / Orange Pi

Topología corta (LAN `192.168.1.0/24`, sin VPN).

```
┌─ BMAX 192.168.1.198 ──────────────────────────────────────┐
│  platform-prometheus :9090 (localhost)                      │
│  platform-node-exporter :9100 (localhost → platform-net)    │
│  platform-cadvisor / platform-alertmanager                  │
│  scrape job precios-hosts ← file_sd/precios-hosts.yml       │
└───────────────┬────────────────────────────┬────────────────┘
                │ :9100                      │ :9100
                ▼                            ▼
         soyo .197                    Orange Pi .90
         precios-node-exporter         precios-node-exporter
         (hwmon/thermal)              (instalar si falta)
```

Grafana: compose en `~/platform-kit/ubuntu/platform/grafana/` — **no** está corriendo. Arrancar solo si hace falta dashboard UI.

App Precios: `/hosts` sigue con `host_stats` → Mongo (CPU/RAM/temp). Prometheus es la capa host metrics estándar.

## Archivos

| Dónde | Path |
|-------|------|
| Repo | `docker-compose.node-exporter.yml` |
| BMAX | `~/platform-kit/ubuntu/platform/prometheus/prometheus.yml` (job `precios-hosts`) |
| BMAX | `~/platform-kit/ubuntu/platform/prometheus/file_sd/precios-hosts.yml` |
| soyo | `~/precios/docker-compose.node-exporter.yml` → contenedor `precios-node-exporter` |

Jobs existentes (`myrentgo-api`, `platform-node`, `platform-cadvisor`) no se tocan.

## Verificar

```bash
# soyo / Pi — métricas locales (bind LAN)
curl -sS http://192.168.1.197:9100/metrics | head
curl -sS http://192.168.1.90:9100/metrics | head   # tras instalar en Pi

# BMAX — targets
ssh -p 2222 richard@192.168.1.198
curl -sS http://127.0.0.1:9090/api/v1/targets | python3 -m json.tool | less
# UI: ssh -L 9090:127.0.0.1:9090 -p 2222 richard@192.168.1.198 → http://localhost:9090/targets

# Reload tras editar file_sd o prometheus.yml
curl -sS -X POST http://127.0.0.1:9090/-/reload
```

## Instalar node_exporter (soyo ya hecho)

```bash
# soyo
ssh richard@192.168.1.197
cd ~/precios
# si falta el yml: copiar desde el repo
NODE_EXPORTER_BIND=192.168.1.197 docker compose -f docker-compose.node-exporter.yml up -d
```

## Orange Pi (requiere SSH con clave autorizada)

Desde Mac/BMAX, `richard@192.168.1.90` responde ping/SSH pero **Permission denied (publickey)** con la clave actual. En el Pi (sesión interactiva / otra clave):

```bash
ssh richard@192.168.1.90   # con la clave que ya uses para cyber-pi
cd ~/precios
# copiar docker-compose.node-exporter.yml del repo si no está
NODE_EXPORTER_BIND=192.168.1.90 docker compose -f docker-compose.node-exporter.yml up -d
curl -sS http://192.168.1.90:9100/metrics | grep -E 'node_hwmon_temp|node_thermal_zone_temp|node_cpu' | head
```

Si Docker pide privilegios: `sudo usermod -aG docker "$USER"` y re-login (o `sudo docker compose ...`).

Tras eso, en BMAX el target `192.168.1.90:9100` (label `host=orange-pi`) debe pasar a **up**.

## Recrear Prometheus en BMAX (compose 1.29)

Si `docker-compose up -d` falla con `KeyError: ContainerConfig`:

```bash
cd ~/platform-kit/ubuntu/platform/prometheus
docker rm -f platform-prometheus
# si queda un nombre raro tipo *_platform-prometheus:
docker ps -aq --filter ancestor=prom/prometheus:v3.2.1 | xargs -r docker rm -f
docker-compose up -d
```

Volumen de datos: `prometheus_prometheus_data`.
