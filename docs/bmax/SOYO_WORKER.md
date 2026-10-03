# Worker de scrape en mini PC «soyo» → Mongo BMAX

Plan concreto para mover los **crons de batch** (`retail batch` / `retail indice`) al mini PC **soyo**, manteniendo **UI, Redis, Qdrant y Mongo** en BMAX. La web sigue en `precios.meincart.com` detrás de platform-caddy.

Contexto actual (BMAX): ver [BMAX_PRODUCCION.md](./BMAX_PRODUCCION.md). Compose de referencia: `docker-compose.prod.yml` (mongo/redis/qdrant/web **sin** `ports:` al host). Cron host: `scripts/install-host-cron.sh` + `scripts/ofertas-diarias-bmax.sh` (hace `docker exec precios-web …`). Horario: `retail/batch/programacion.json`.

---

## 1. Objetivo y arquitectura

**Objetivo:** el scrape pesado (CPU, red hacia tiendas, Playwright opcional) corre en soyo; la persistencia y la búsqueda siguen en BMAX.

```
                    Internet (tiendas)
                           │
                           ▼
┌────────────────┐   scrape / indice    ┌─────────────────────────────────────┐
│  soyo (worker) │ ───────────────────► │  BMAX (LAN o VPN)                   │
│                │                      │                                     │
│  cron host     │   MONGODB_URI ──────►│  precios-mongo  (datos + batch_runs)│
│  venv o slim   │   REDIS_URL ────────►│  precios-redis  (caché + pindex)    │
│  compose       │   QDRANT_URL ───────►│  precios-qdrant (opcional batch)    │
│  SIN mongo/    │                      │  precios-web :8080 → platform-caddy │
│  redis/qdrant  │                      │  UI /cron / búsqueda                │
└────────────────┘                      └─────────────────────────────────────┘
         ▲                                         │
         │                         Cloudflare Tunnel │
         │                                         ▼
    cron diario                          precios.meincart.com
    (programacion.json)                  «Iniciar ahora» = thread en web (fase 1)
```

| Componente | Dónde vive | Notas |
|------------|------------|--------|
| Cron programado por grupo | **soyo** | Adaptar wrapper local (sin `docker exec`) |
| `retail batch` / `retail indice` | **soyo** | Escribe Mongo BMAX; índice caliente → Redis BMAX |
| UI FastAPI + `/cron` | **BMAX** | `precios-web` |
| Mongo / Redis / Qdrant | **BMAX** | Sin abrir WAN |
| «Iniciar ahora» (fase 1) | **BMAX web** | Thread en `retail/web/jobs.py`; CPU sigue en BMAX |
| Alertas predictivas (`run_on_bmax.sh`) | **BMAX** (recomendado) | Depende de TimesFM/host BMAX; no migrar con el scrape |

---

## 2. Prerrequisitos (red)

Preferir **Tailscale** o **WireGuard** entre soyo y BMAX. Alternativa aceptable: misma LAN (hoy el deploy usa `richard@192.168.1.198:2222` según `BMAX_PRODUCCION.md`), siempre que el firewall no exponga Mongo/Redis a vecinos no confiables.

Anotar antes del cutover:

| Máquina | IP LAN (ejemplo) | IP VPN (Tailscale/WG) | Rol |
|---------|------------------|------------------------|-----|
| BMAX | `192.168.1.198` (SSH `:2222`) | **sin Tailscale/WG** (2026-03-02) | Mongo/Redis/Qdrant + web |
| soyo | _(desconocida — pedir IP/usuario SSH)_ | _(rellenar)_ | Solo worker + cron |

**Inventario BMAX (fase 0, verificado):**

- SSH OK: `richard@192.168.1.198 -p 2222` (`richard-bmax`).
- Tailscale / WireGuard: **no instalados**.
- `precios-mongo` / `precios-redis` / `precios-qdrant`: **sin** `ports:` al host; auth Mongo **ausente**; Redis `requirepass` vacío.
- Host ya tiene `127.0.0.1:27017` y `127.0.0.1:6379` (platform) → el override soyo usa **27018/6380** en la IP VPN.
- Cron host activo: bloque `# retail-ofertas-begin` … 19× `ofertas-diarias-bmax.sh <grupo>` (00:00–13:30 stagger 45m) + `run_on_bmax.sh` 21:30.

Comprobar desde soyo (sustituir IPs):

```bash
ping -c 2 <BMAX_VPN_IP>
# Tras exponer puertos en §3:
nc -vz <BMAX_VPN_IP> 27017
nc -vz <BMAX_VPN_IP> 6379
# Qdrant solo si el batch lo usa en tu .env
nc -vz <BMAX_VPN_IP> 6333
```

Reglas:

- Tráfico Mongo/Redis/Qdrant **solo** desde la IP VPN/LAN de soyo (y localhost en BMAX si hace falta diagnóstico).
- **No** publicar 27017 / 6379 / 6333 en `0.0.0.0` ni en la IP WAN / Cloudflare.

---

## 3. Cambios en BMAX: exponer Mongo (y Redis) solo en VPN/LAN

Hoy `docker-compose.prod.yml` **no** mapea puertos de `mongo`, `redis` ni `qdrant` al host: solo hablan por la red interna de Docker (`precios-mongo`, `precios-redis`, `precios-qdrant`). `precios-web` usa `expose: "8080"` y se une a `platform-net` vía `docker-compose.prod.platform.yml`. Eso es correcto para la UI; el worker remoto necesita un bind **acotado**.

### 3.1 Auth y bind (recomendado)

1. **Mongo:** habilitar usuario/contraseña (o al menos bindIp + auth) y usar URI con credenciales desde soyo, p. ej.  
   `mongodb://user:pass@<BMAX_VPN_IP>:27017/?authSource=admin`  
   El contenedor `web` puede seguir con `mongodb://precios-mongo:27017` en la red Docker; el bind al host es solo para soyo.
2. **Redis:** preferible `requirepass` y URI `redis://:pass@<BMAX_VPN_IP>:6379/0`. Actualizar `REDIS_URL` del web si cambias la contraseña interna, o publicar un puerto host autenticado distinto del Redis sin auth de la red Docker (más simple: misma pass en el contenedor y en soyo).
3. **Qdrant:** el batch/embeddings pueden necesitarlo; si soyo no vectoriza, se puede omitir el puerto. Si sí, bind solo VPN + API key de Qdrant si la activas.

### 3.2 Cómo publicar puertos sin abrir WAN

En un override (p. ej. `docker-compose.prod.soyo-access.yml`, **no** mezclar con WAN):

```yaml
# Ejemplo — sustituir BMAX_VPN_IP por la IP Tailscale/WG/LAN de BMAX
services:
  mongo:
    ports:
      - "<BMAX_VPN_IP>:27017:27017"
  redis:
    ports:
      - "<BMAX_VPN_IP>:6379:6379"
  # qdrant:
  #   ports:
  #     - "<BMAX_VPN_IP>:6333:6333"
```

Arranque (junto al compose actual):

```bash
cd ~/precios
docker compose \
  -f docker-compose.prod.yml \
  -f docker-compose.prod.platform.yml \
  -f docker-compose.prod.soyo-access.yml \
  up -d
```

Integrar el archivo extra en `scripts/deploy-prod.sh` / menú cuando el override exista en el servidor, para que un deploy no lo olvide.

**Importante:**

- Usar la IP concreta de la interfaz VPN/LAN, **nunca** `0.0.0.0:27017`.
- Si Docker en Linux a veces ignora el bind esperado, complementar con **ufw/iptables**: allow 27017/6379 solo desde `<SOYO_VPN_IP>`; deny el resto.
- Conflicto histórico: el host BMAX ya puede tener Mongo/Redis de plataforma en `127.0.0.1:27017` / `:6379` (ver `docs/CHANGES_BMAX.md`). Por eso el compose de **dev** usó `27018`/`6380`. En prod actual **no** hay mapeo; al añadir el override, elige puertos libres en el host si choca (p. ej. publicar `27018→27017` y apuntar soyo a ese puerto).
- `precios-web` debe seguir resolviendo `precios-mongo` / `precios-redis` por nombre Docker; **no** cambiar su `.env` a la IP VPN salvo que sepas lo que haces.

### 3.3 Firewall (checklist)

- [ ] `ss -lntp` / `docker ps` muestra bind solo en IP VPN/LAN.
- [ ] Desde un host fuera de la VPN: conexión a 27017/6379 **falla**.
- [ ] Desde soyo por VPN: conexión **OK** con auth.
- [ ] WAN / Cloudflare Tunnel: sin rutas nuevas a Mongo/Redis.

---

## 4. Setup en soyo

### 4.1 Código

```bash
# En soyo
git clone <url-del-repo> ~/precios   # o rsync desde Mac/BMAX
cd ~/precios
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt   # o el lock que use el proyecto
```

Alternativa: compose **slim worker** (solo imagen app, sin servicios `mongo`/`redis`/`qdrant`) que lea el mismo `.env` remoto. No hace falta `docker-compose.prod.yml` completo en soyo.

### 4.2 `.env` en soyo (apunta a BMAX)

```env
MONGODB_URI=mongodb://USER:PASS@<BMAX_VPN_IP>:27017
MONGODB_DB=scraping
REDIS_URL=redis://:PASS@<BMAX_VPN_IP>:6379/0
QDRANT_URL=http://<BMAX_VPN_IP>:6333
QDRANT_COLLECTION=products

# Opcional: capturas en alertas (CPU/disco en soyo)
# OFFER_SCREENSHOTS=0
# Ver docs/offer_screenshots.md — Playwright/Chromium si se activa
```

No hace falta `RETAIL_SECRET` ni admin en soyo si **no** levantas la UI allí. Sí hace falta lo que el batch lea (pausas, proxies, `ADAPTIVE_SCRAPING`, etc.).

Copiar también `retail/batch/programacion.json` (y `reglas_ofertas.json` si el batch las usa) para que el wrapper local lea el mismo horario/flags que la UI edita en BMAX — o sincronizar ese JSON en cada deploy (hoy en BMAX es bind mount y `sync-to-precios.sh` lo conserva en el servidor).

### 4.3 Wrapper local (sin `docker exec`)

`scripts/ofertas-diarias-bmax.sh` asume contenedor `precios-web`. En soyo usar la lógica de `scripts/ofertas-diarias.sh` (venv + `retail batch`) **más** las protecciones útiles del wrapper BMAX:

- `flock` por grupo y cupos (`ofertas-slot-*.lock`) para no saturar.
- Renovación diaria única de `retail indice` (`logs/indice-YYYY-MM-DD.done`).
- Respeto de `enabled` / `paused` / `source` / `pause` / `batch_budget_minutes` vía `load_schedule()`.
- Grupo `retail`: `ADAPTIVE_SCRAPING=0` y presupuesto completo (como en el wrapper BMAX).

Nombre sugerido: `scripts/ofertas-diarias-soyo.sh` (copiar de `ofertas-diarias-bmax.sh` sustituyendo cada `docker exec … precios-web` por invocación local `retail …` con el venv activado o `PATH` al venv).

Smoke manual:

```bash
cd ~/precios && source .venv/bin/activate
set -a && source .env && set +a
retail indice          # Mongo BMAX → Redis BMAX
retail batch --grupo farmacias --source scrape --pausa 3 --presupuesto-minutos 15
```

---

## 5. Migración del cron

### 5.1 Instalar cron en soyo

Reutilizar la idea de `scripts/install-host-cron.sh`: bloque `# retail-ofertas-begin` … `# retail-ofertas-end`, `CRON_TZ=America/Santiago`, una línea por grupo según `programacion.json` (`hour`/`minute`, `groups.mode: per_group`, `stagger_minutes`).

Hoy el JSON de ejemplo tiene `"hour": 0`, `"minute": 0`, `"stagger_minutes": 45`, `"enabled": true`.

Adaptar el instalador para apuntar a `ofertas-diarias-soyo.sh` (no al script BMAX). **No** instalar en soyo la línea de `run_on_bmax.sh` (alertas predictivas / TimesFM): déjala en BMAX o desactívala conscientemente.

```bash
# En soyo, tras adaptar el script
bash scripts/install-host-cron-soyo.sh   # o flag en el instalador
crontab -l | sed -n '/retail-ofertas-begin/,/retail-ofertas-end/p'
```

### 5.2 Desactivar cron en BMAX

Orden crítico: **primero** soyo OK en smoke, **después** quitar BMAX, para no tener doble scrape.

En BMAX:

```bash
cd ~/precios
# Opción A: programacion.json enabled=false y reinstalar (quita líneas de ofertas)
# Opción B: quitar a mano el bloque retail-ofertas-* del crontab
crontab -l   # verificar que no queden ofertas-diarias-bmax.sh

# Ojo: prod-menu opción 8 / deploy-prod.sh vuelven a llamar install-host-cron.sh
# y REINSTALAN el cron en BMAX si programacion.json sigue enabled=true.
```

Acciones duraderas en BMAX:

1. Dejar `enabled: true` en el JSON (la UI/soyo lo necesitan) pero **modificar** `install-host-cron.sh` / `deploy-prod.sh` / opción 8 del `prod-menu` para **no** reinstalar líneas de batch en BMAX (solo predictive, o nada de ofertas), **o**
2. Documentar un flag `HOST_BATCH_CRON=0` en `.env` de BMAX que el instalador respete.

Hasta que exista ese flag, tras cada deploy revisar `crontab -l` en BMAX.

---

## 6. «Iniciar ahora» en `/cron` (honestidad fase 1)

Hoy el botón llama `POST /api/admin/cron-batches/{group}/start` → `start_group_batch` en `retail/web/jobs.py`, que reserva en Mongo `batch_runs` y lanza un **`threading.Thread` dentro de `precios-web`**.

**Fase 1 (este plan):** el disparo manual **sigue en BMAX**. La CPU del scrape manual permanece en el servidor web. El cron programado es el que se alivia moviendo a soyo.

**Fase 2 (futuro, no implementada aquí):** encolar trabajo (Redis/RQ, cola Mongo, o SSH/HTTP a soyo) para que «Iniciar ahora» despierte el worker remoto. Hasta entonces, no afirmar que el botón usa soyo.

La UI `/cron` **sí** verá corridas hechas en soyo porque ambas escriben el mismo Mongo (`batch_runs`).

---

## 7. Deploy dual (actualizar código en soyo)

| Canal | BMAX (hoy) | Soyo |
|-------|------------|------|
| Push a `main` | Runner self-hosted `bmax` → `sync-to-precios.sh` + `deploy-prod.sh` (`.github/workflows/deploy-bmax.yml`) | No automático al inicio |
| Manual | `push-to-server.sh` / prod-menu | `git pull` en `~/precios` + `pip install -r …` si cambian deps |
| Alternativa | — | `rsync` desde Mac (mismo espíritu que `scripts/sync-to-precios.sh`, excluyendo `.env` y `programacion.json` remoto si no quieres pisarlo) |

Flujo mínimo tras cambios de batch:

```bash
# soyo
cd ~/precios && git pull
source .venv/bin/activate && pip install -r requirements.txt
# reiniciar nada si solo hay cron+venv; si usas contenedor worker: compose up -d --build
```

Más adelante: segundo runner GH (`soyo`) o un job que haga SSH/rsync a soyo después del deploy BMAX. No es bloqueante para el cutover.

Mantener **misma revisión de código** (o al menos misma lógica de `retail/batch`) entre soyo y la imagen web para no divergir cursores/`batch_runs`.

---

## 8. Checklist de cutover (ordenado) y rollback

### Cutover

1. [ ] VPN estable soyo ↔ BMAX; anotar IPs.
2. [ ] Auth Mongo (y Redis); override compose con bind a IP VPN/LAN; firewall.
3. [ ] Verificar desde soyo: ping + `mongosh` / `redis-cli` + auth.
4. [ ] Clonar/sync repo en soyo; venv; `.env` con URIs BMAX.
5. [ ] Adaptar wrapper `ofertas-diarias-soyo.sh` + instalador cron soyo.
6. [ ] Smoke: un grupo corto (§9); `/cron` muestra `batch_runs`; búsqueda OK.
7. [ ] Instalar crontab en soyo; validar `crontab -l`.
8. [ ] **Desactivar** líneas `ofertas-diarias-bmax.sh` en BMAX; asegurar que deploy no las reinstale.
9. [ ] Dejar en BMAX (si aplica) solo predictive `run_on_bmax.sh` u omitir a conciencia.
10. [ ] Primer día completo: revisar logs en soyo (`logs/ofertas-diarias-*.log`) y `/cron`.
11. [ ] Documentar IPs/puertos en el `.env` del servidor (sin commitear secretos).

### Rollback

1. Reinstalar cron en BMAX: `cd ~/precios && ./prod-menu.sh` → opción 8 (o `bash scripts/install-host-cron.sh`).
2. En soyo: `crontab -r` selectivo (quitar bloque `retail-ofertas-*`) o `enabled` local.
3. Opcional: quitar override `docker-compose.prod.soyo-access.yml` y cerrar puertos/firewall.
4. Confirmar una corrida vía `docker exec precios-web` / wrapper BMAX otra vez.

---

## 9. Pruebas de validación

1. **Smoke un grupo** (p. ej. `farmacias` o el más pequeño) desde soyo con presupuesto corto.
2. En `https://precios.meincart.com/cron` (admin): el grupo aparece en `batch_runs` (progreso / done / failed).
3. **Búsqueda** en la UI: sigue usando el mismo Redis BMAX (caché + `retail:pindex:`). Tras `retail indice` en soyo, el hash/meta en Redis debe actualizarse; una búsqueda conocida (p. ej. genérico del índice) no debe degradarse.
4. Confirmar que **no** hay doble corrida: BMAX sin cron de ofertas + soyo con cron.
5. Negativo: host sin VPN no alcanza Mongo/Redis.

---

## 10. Esfuerzo y riesgos

### Esfuerzo (orden de magnitud)

| Bloque | Tiempo orientativo |
|--------|--------------------|
| VPN + firewall + bind compose + auth | 2–4 h |
| Soyo: venv, `.env`, wrapper sin docker exec, cron | 2–4 h |
| Flag/guardas para que deploy BMAX no reinstale cron batch | 1–2 h |
| Cutover + validación + primer día vigilado | 2–3 h |
| **Total fase 1** | **~1–1,5 días** |
| Fase 2 (encolar «Iniciar ahora» → soyo) | +1–3 días (diseño + UI) |

### Riesgos

| Riesgo | Mitigación |
|--------|------------|
| Doble scrape (BMAX + soyo) | Cutover ordenado; flag `HOST_BATCH_CRON=0`; revisar crontab tras cada deploy |
| Exponer Mongo/Redis a WAN | Bind a IP VPN; ufw; nunca `0.0.0.0`; auth obligatoria |
| Conflicto de puertos en host BMAX | Elegir 27018/6380 si 27017/6379 están ocupados |
| Latencia VPN en índice/batch | Preferir Tailscale en LAN; medir; Redis/Mongo en misma VPN |
| Drift de código soyo vs imagen web | `git pull` disciplinado o runner; misma rama `main` |
| «Iniciar ahora» sigue cargando BMAX | Esperado en fase 1; no venderlo como migrado |
| `programacion.json` divergente | Sync desde BMAX o montaje/copia consciente |
| Predictive/TimesFM roto si se mueve a soyo | Dejar `run_on_bmax.sh` en BMAX |

---

## Referencias en el repo

| Archivo | Uso |
|---------|-----|
| `docker-compose.prod.yml` | Servicios sin `ports:` host hoy |
| `docker-compose.prod.platform.yml` | Solo `precios-web` → `platform-net` |
| `docker-compose.prod.soyo-access.yml` | Bind Mongo/Redis solo si `BMAX_VPN_IP` (puertos 27018/6380) |
| `docker-compose.worker.soyo.yml` | Imagen slim opcional en soyo (preferir venv+cron) |
| `scripts/ofertas-diarias-bmax.sh` | Cron BMAX (`docker exec`) |
| `scripts/ofertas-diarias-soyo.sh` | Cron soyo (venv, sin `docker exec`) |
| `scripts/install-host-cron.sh` | Crontab BMAX; respeta `HOST_BATCH_CRON=0` |
| `scripts/install-host-cron-soyo.sh` | Crontab soyo (sin predictive) |
| `scripts/bmax-prepare-soyo-db-auth.sh` | Prepara usuario Mongo + Redis pass (sin abrir puertos) |
| `.env.soyo.example` | Plantilla `.env` del worker |
| `retail/batch/programacion.json` | Hora, stagger, enabled, source, pause |
| `docs/bmax/BMAX_PRODUCCION.md` | Deploy y cron actuales en BMAX |
| `retail/web/jobs.py` | «Iniciar ahora» = thread en web |
| `docs/offer_screenshots.md` | `OFFER_SCREENSHOTS` opcional |
