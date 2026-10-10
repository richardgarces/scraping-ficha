from __future__ import annotations

import argparse
import sys
from pathlib import Path

from retail.export import save_products
from retail.http import HttpError
from retail.models import Product
from retail.registry import get_client, list_stores
from retail.scaffold import PLATFORMS, scaffold_store


def store_main(store_id: str, argv: list[str] | None = None) -> int:
    spec = next(item for item in list_stores() if item.id == store_id)
    args = _build_parser(spec).parse_args(argv)
    try:
        with get_client(store_id, delay=args.delay, timeout=args.timeout) as client:
            products = _run(client, args)
    except (HttpError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    path = save_products(products, args.salida)
    _print_summary(products, path)
    return 0


def _store_entrypoint(store_id: str):
    def _main(argv: list[str] | None = None) -> int:
        return store_main(store_id, argv)

    _main.__name__ = f"main_{store_id}"
    _main.__qualname__ = _main.__name__
    return _main


def unified_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="retail",
        description="Scraper unificado de retail chileno. Fuentes en retail/sources/, motores en retail/platforms/.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    listed = sub.add_parser("tiendas", help="Listar fuentes registradas")
    listed.set_defaults(command="tiendas")
    nueva = sub.add_parser("nueva", aliases=["scaffold"], help="Crear el esqueleto de una fuente")
    nueva.add_argument("store_id", help="ID en snake_case, por ejemplo mercadolibre")
    nueva.add_argument("--titulo", required=True, help='Nombre visible, por ejemplo "Mercado Libre Chile"')
    nueva.add_argument("--sitio", required=True, help="Host, por ejemplo www.mercadolibre.cl")
    nueva.add_argument("--plataforma", choices=PLATFORMS, default="custom", help="Motor: custom, vtex, shopify o magento")
    nueva.add_argument("--marca", default=None, help="Marca por defecto (útil en VTEX)")
    nueva.add_argument("--categoria-extra", action="store_true", help="Agregar --nombre a categoria")
    nueva.set_defaults(command="nueva")
    web = sub.add_parser("web", help="Interfaz web para comparar precios entre tiendas")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8080)
    web.set_defaults(command="web")
    batch = sub.add_parser("batch", help="Recorrer el catálogo, guardar precios y emitir alertas de oferta")
    batch.add_argument(
        "grupo_pos",
        nargs="?",
        default=None,
        help="Grupo de tiendas (alternativa a --grupo), p. ej. tecnologia",
    )
    batch.add_argument(
        "--grupo",
        default=None,
        help="Solo tiendas de ese grupo (Mongo store_categories / registry)",
    )
    batch.add_argument(
        "--tienda",
        default=None,
        help="Solo esa tienda: consultas de su grupo (y su árbol de categorías, si existe)",
    )
    batch.add_argument("--catalogo", default=None, help="JSON de productos (default: catálogo de electrónicos)")
    batch.add_argument("--reglas", default=None, help="JSON de reglas de oferta")
    batch.add_argument("--source", choices=["scrape", "db", "both"], default="both")
    batch.add_argument("-n", "--max", type=int, default=6, help="Productos por tienda en cada búsqueda")
    batch.add_argument("--delay", type=float, default=1.0)
    batch.add_argument("--pausa", type=float, default=2.0, help="Pausa entre productos del catálogo")
    batch.add_argument(
        "--presupuesto-minutos",
        type=float,
        default=None,
        help="Duración máxima del grupo; continúa desde ese punto en la próxima corrida",
    )
    batch.add_argument("--limit", type=int, default=None, help="Procesar solo los primeros N ítems")
    batch.add_argument("--ids", default=None, help="IDs del catálogo separados por coma")
    batch.add_argument("--dry-run", action="store_true", help="Listar el catálogo sin scrapear")
    batch.set_defaults(command="batch")
    recode = sub.add_parser(
        "recodificar",
        help="Recalcular el código de comparación de los productos ya guardados",
    )
    recode.add_argument("--dry-run", action="store_true", help="Contar los cambios sin escribir")
    recode.set_defaults(command="recodificar")
    urls = sub.add_parser(
        "normalizar-urls",
        help="Corregir URLs antiguas de productos ya guardados",
    )
    urls.add_argument("--stores", default="cruzverde,sodimac", help="Tiendas separadas por coma")
    urls.add_argument("--dry-run", action="store_true", help="Contar los cambios sin escribir")
    urls.set_defaults(command="normalizar-urls")
    indice = sub.add_parser(
        "indice",
        aliases=["pindex"],
        help="Cargar o consultar el índice de productos genéricos en Redis",
    )
    indice.add_argument(
        "accion",
        nargs="?",
        default="cargar",
        choices=["cargar", "load", "letra", "resolver", "resolve", "sin-match", "unmatched"],
        help="cargar recarga Redis desde Mongo; letra lista; resolver identifica; sin-match muestra consultas sin genérico",
    )
    indice.add_argument("valor", nargs="?", default="", help="Letra o consulta, según la acción")
    indice.set_defaults(command="indice")
    for spec in list_stores():
        store_parser = sub.add_parser(spec.id, help=f"Scrapear {spec.title}")
        _add_store_subcommands(store_parser, spec)
        store_parser.set_defaults(store_id=spec.id)
    args = parser.parse_args(argv)
    if args.command == "tiendas":
        for spec in list_stores():
            engine = spec.platform or "custom"
            print(f"{spec.id:14} {engine:8} {spec.title}  ({spec.site})")
        return 0
    if args.command in {"nueva", "scaffold"}:
        try:
            path = scaffold_store(
                args.store_id,
                args.titulo,
                args.sitio,
                extra_category=args.categoria_extra,
                platform=args.plataforma,
                brand=args.marca,
            )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(f"Creada {path}")
        if args.plataforma == "custom":
            print("Implementa _iter_listing() y, si quieres atajo CLI, agrégalo en pyproject.toml.")
        else:
            print("Fuente lista. El atajo CLI aparece al reinstalar: pip install -e .")
        return 0
    if args.command == "web":
        return serve_web(args.host, args.port)
    if args.command == "batch":
        return run_catalog_batch(args)
    if args.command == "recodificar":
        return recode_products(dry_run=args.dry_run)
    if args.command == "normalizar-urls":
        return normalize_saved_urls(stores=args.stores, dry_run=args.dry_run)
    if args.command == "indice":
        return run_indice(args)
    try:
        with get_client(args.store_id, delay=args.delay, timeout=args.timeout) as client:
            products = _run(client, args)
    except (HttpError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    path = save_products(products, args.salida)
    _print_summary(products, path)
    return 0


def _build_parser(spec) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=spec.id,
        description=f"Scraper de productos públicos de {spec.title} ({spec.site}).",
    )
    _add_store_subcommands(parser, spec)
    return parser


def _add_store_subcommands(parser: argparse.ArgumentParser, spec) -> None:
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("--delay", type=float, default=1.0)
    shared.add_argument("--timeout", type=float, default=30.0)
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("buscar", aliases=["search"], parents=[shared], help="Buscar por texto")
    search.add_argument("query")
    _add_list_args(search, spec)

    category = sub.add_parser("categoria", aliases=["category"], parents=[shared], help="Listar categoría")
    category.add_argument("category_id", help=spec.category_help)
    if spec.extra_category:
        category.add_argument("--nombre", default="productos", help="Slug de la categoría")
    _add_list_args(category, spec)

    product = sub.add_parser("producto", aliases=["product"], parents=[shared], help="Ficha de producto")
    product.add_argument("product_id")
    product.add_argument("-o", "--salida", default="output/producto.json")

    url = sub.add_parser("url", parents=[shared], help="Scrapear una URL de la tienda")
    url.add_argument("value")
    _add_list_args(url, spec)


def _add_list_args(parser: argparse.ArgumentParser, spec) -> None:
    parser.add_argument("-p", "--paginas", type=int, default=1)
    parser.add_argument("-n", "--max", type=int, default=None)
    parser.add_argument("--orden", choices=list(spec.sort_map), default=None)
    parser.add_argument("--detalle", action="store_true")
    parser.add_argument("-o", "--salida", default="output/productos.csv")


def _run(client, args: argparse.Namespace) -> list[Product]:
    kwargs = {
        "max_pages": getattr(args, "paginas", 1),
        "max_items": getattr(args, "max", None),
        "sort": getattr(args, "orden", None),
        "detalle": getattr(args, "detalle", False),
    }
    if args.command in {"buscar", "search"}:
        return client.scrape(args.query, **kwargs)
    if args.command in {"categoria", "category"}:
        return client.scrape(client.category_target(args), **kwargs)
    if args.command in {"producto", "product"}:
        return client.scrape(args.product_id, max_pages=1)
    return client.scrape(args.value, **kwargs)


def recode_products(*, dry_run: bool = False) -> int:
    """Reescribe compare_code en Mongo con las reglas de emparejamiento actuales.

    Los documentos guardan el código con que se calcularon, así que al cambiar
    las reglas el catálogo sigue agrupando como antes hasta que esa búsqueda se
    repite. Esto lo pone al día de una vez.
    """
    from retail.compare import compare_code
    from retail.search import connect_repo

    repo = connect_repo()
    if repo is None:
        print("MongoDB no disponible.", file=sys.stderr)
        return 1
    try:
        from pymongo import UpdateOne

        pending: list[UpdateOne] = []
        total = 0
        for document in repo.collection.find({}, {"thumbnail": 0, "price_history": 0}):
            total += 1
            fresh = compare_code(Product.from_dict(document))
            if fresh == document.get("compare_code"):
                continue
            pending.append(UpdateOne({"_id": document["_id"]}, {"$set": {"compare_code": fresh}}))
        if pending and not dry_run:
            repo.collection.bulk_write(pending, ordered=False)
        verb = "cambiarían" if dry_run else "actualizados"
        print(f"{len(pending)} de {total} productos {verb}.")
        return 0
    finally:
        repo.close()


def normalize_saved_urls(*, stores: str = "cruzverde,sodimac", dry_run: bool = False) -> int:
    """Repara las URLs históricas con las mismas reglas usadas al guardar."""
    from retail.models import normalize_product_url
    from retail.search import connect_repo

    wanted = [item.strip().lower() for item in stores.split(",") if item.strip()]
    repo = connect_repo()
    if repo is None:
        print("MongoDB no disponible.", file=sys.stderr)
        return 1
    try:
        from pymongo import UpdateOne

        pending: list[UpdateOne] = []
        scanned = 0
        for document in repo.collection.find(
            {"store": {"$in": wanted}},
            {"store": 1, "name": 1, "url": 1},
        ):
            scanned += 1
            current = document.get("url")
            fresh = normalize_product_url(document.get("store"), current, document.get("name"))
            if not fresh or fresh == current:
                continue
            pending.append(UpdateOne({"_id": document["_id"]}, {"$set": {"url": fresh}}))
        if pending and not dry_run:
            repo.collection.bulk_write(pending, ordered=False)
        verb = "cambiarían" if dry_run else "actualizadas"
        print(f"{len(pending)} de {scanned} URLs {verb} ({', '.join(wanted)}).")
        return 0
    finally:
        repo.close()


def run_catalog_batch(args: argparse.Namespace) -> int:
    from retail.batch.runner import run_batch

    ids = [item.strip() for item in args.ids.split(",") if item.strip()] if args.ids else None
    catalog = Path(args.catalogo) if args.catalogo else None
    rules = Path(args.reglas) if args.reglas else None
    grupo = args.grupo or getattr(args, "grupo_pos", None)
    tienda = getattr(args, "tienda", None)
    if tienda and grupo:
        print("Error: usa --tienda o --grupo, no ambos.", file=sys.stderr)
        return 1
    try:
        summary = run_batch(
            catalog_path=catalog,
            rules_path=rules,
            source=args.source,
            max_items=args.max,
            delay=args.delay,
            pause=args.pausa,
            limit=args.limit,
            ids=ids,
            grupo=grupo,
            tienda=tienda,
            dry_run=args.dry_run,
            time_budget_minutes=args.presupuesto_minutos,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if summary.get("tienda"):
        label = f" · tienda {summary['tienda']}"
    elif summary.get("grupo"):
        label = f" · grupo {summary['grupo']}"
    else:
        label = ""
    print(
        f"Procesados {len(summary['searches'])} productos{label} · "
        f"{summary.get('alert_count') or 0} alertas"
    )
    for row in summary["searches"]:
        if row.get("error"):
            print(f"  ! {row.get('id')}: {row['error']}")
        elif args.dry_run:
            print(f"  {row.get('id')}: {row.get('query')}")
        else:
            saved = row.get("saved") or {}
            print(
                f"  {row.get('id')}: {row.get('offers', 0)} ofertas · "
                f"Mongo +{saved.get('upserted') or 0} ~{saved.get('modified') or 0} · "
                f"{row.get('alerts', 0)} alertas"
            )
    if summary.get("interrupted"):
        from retail.batch.group_scope import INTERRUPT_EXIT_CODE

        print(
            "Corrida interrumpida (deploy/SIGTERM); cursor guardado para reintento/continuación.",
            file=sys.stderr,
        )
        return INTERRUPT_EXIT_CODE
    return 0


def run_indice(args: argparse.Namespace) -> int:
    from retail.index.products import ensure_loaded, products_for_letter, resolve
    from retail.registry import GROUP_TITLES

    accion = args.accion or "cargar"
    if accion in {"cargar", "load"}:
        meta = ensure_loaded(force=True)
        backend = "Redis" if meta.get("backend") == "redis" else "memoria"
        origen = "Mongo" if meta.get("source") == "mongo" else "JSON"
        print(
            f"{meta.get('count') or 0} productos genéricos en {backend} desde {origen} "
            f"(versión {meta.get('version')}, hash {meta.get('seed_hash')})."
        )
        try:
            from retail.store_categories import ensure_store_categories

            cats = ensure_store_categories()
            print(
                f"Categorías de tiendas: {cats.get('count') or 0} en "
                f"{cats.get('source') or 'registry'} "
                f"(+{cats.get('upserted') or 0} nuevas)."
            )
        except Exception as exc:
            print(f"Categorías de tiendas: no se pudieron sincronizar ({exc})")
        if meta.get("backend") != "redis":
            print("Redis no está disponible; el índice queda en memoria hasta que Redis esté arriba.")
        return 0
    if accion in {"sin-match", "unmatched"}:
        from retail.search import connect_repo

        store = connect_repo()
        if store is None:
            print("MongoDB no disponible.", file=sys.stderr)
            return 1
        try:
            rows = store.unmatched_product_index_queries(limit=50)
        finally:
            store.close()
        if not rows:
            print("Sin consultas sin match.")
            return 0
        for item in rows:
            query = item.get("query") or ""
            folded = item.get("folded") or ""
            when = item.get("created_at")
            stamp = when.isoformat() if hasattr(when, "isoformat") else str(when or "")
            print(f"{stamp:25} {query}  ({folded})")
        return 0
    if accion == "letra":
        letter = (args.valor or "").strip()
        if not letter:
            print("Indica una letra, por ejemplo: retail indice letra t", file=sys.stderr)
            return 1
        rows = products_for_letter(letter)
        if not rows:
            print(f"Sin productos en la letra {letter}.")
            return 0
        for item in rows:
            print(f"{item.id:20} {item.name}")
        return 0
    query = (args.valor or "").strip()
    if not query:
        print('Indica una consulta, por ejemplo: retail indice resolver "tv 50 pulgadas"', file=sys.stderr)
        return 1
    found = resolve(query)
    if found is None:
        print(f"Sin producto genérico para «{query}».")
        return 0
    groups = ", ".join(GROUP_TITLES.get(group, group) for group in found.groups)
    print(f"«{query}» → {found.id} ({found.name}) · {groups}")
    return 0


def serve_web(host: str, port: int) -> int:
    try:
        import uvicorn
    except ImportError:
        print("Falta uvicorn. Instala el paquete: pip install -e .", file=sys.stderr)
        return 1

    print(f"Comparador en http://{host}:{port}")
    uvicorn.run("retail.web.app:app", host=host, port=port, reload=True)
    return 0


def _print_summary(products: list[Product], path: Path) -> None:
    print(f"Guardados {len(products)} productos en {path}")
    for product in products[:8]:
        price = f"${product.price:,}".replace(",", ".") if product.price else "s/precio"
        extra = f" · {product.brand}" if product.brand else ""
        ident = product.sku_id or product.product_id
        print(f"  [{ident}] {product.name}{extra} · {price}")
    if len(products) > 8:
        print(f"  ... y {len(products) - 8} más")


def __getattr__(name: str):
    if name.startswith("main_"):
        return _store_entrypoint(name.removeprefix("main_"))
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


for _spec in list_stores():
    globals()[f"main_{_spec.id}"] = _store_entrypoint(_spec.id)
