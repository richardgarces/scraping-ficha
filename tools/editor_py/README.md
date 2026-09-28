Editor Py — prototipo de curación de productos

Instrucciones rápidas:

- Construir y levantar (local):

```bash
docker compose build
docker compose up -d
```

- Ejecutar sin Docker:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

Variables de entorno:
- `MONGODB_URI` (opcional): cadena de conexión MongoDB. Por defecto usa `mongodb://precios-mongo:27017/precios`.

Rutas útiles:
- `/admin` — listado y edición
- `/admin/export_opencompare` — descarga JSON OpenCompare PoC
Editor de curación (prototipo)
=================================

Pequeño prototipo en Flask para curar y normalizar campos extraídos por los scrapers.

Requisitos
- Python 3.10+
- `pip install -r requirements.txt` (o `pymongo` si quiere usar Mongo)

Ejecutar (modo local usando `products.json` si no hay Mongo):

```bash
python3 app.py
# acceso: http://127.0.0.1:5008/admin
```

Si quieres usar la base de datos del proyecto, exporta `MONGODB_URI` apuntando a la base y el prototipo hará upsert en la colección `products`.

Uso
- Listar productos -> Editar -> Guardar. Guarda en Mongo si está configurado, o en `products.json`.
