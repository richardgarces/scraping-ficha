Prueba local del proxy pool

1) Exportar una lista de proxies (o usa proxies de prueba):

export PROXY_LIST="http://user:pass@127.0.0.1:3128,http://127.0.0.1:3129"
export PROXY_STICKY_TTL=60

2) Compilar worker:

cd scraping/worker
go build -o worker

3) Ejecutar worker en modo test (consume una URL colocada manualmente en Redis):

# desde otra terminal, insertar URL
redis-cli -u redis://localhost:6379 ZADD schedule:urls 0 "http://example.com/test"

# ejecutar worker
./worker

4) Observa en logs la asignación de proxy y que `runner.py` ejecuta con env vars HTTP_PROXY/HTTPS_PROXY.

Notas:
- Para pruebas locales puedes usar tinyproxy o mitmproxy como proxy local.
- El runner recibirá las variables de entorno `HTTP_PROXY`/`HTTPS_PROXY` y las respetará si usa `requests` o librerías que respeten variables de entorno.
