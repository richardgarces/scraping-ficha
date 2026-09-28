from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_tiendacopec_target = parse_shopify_target

TiendacopecStore = make_shopify_store(
    store_id="tiendacopec",
    title="Tienda Copec",
    site="www.tiendacopec.cl",
    base="https://www.tiendacopec.cl",
    category_help="Handle de colección Shopify, por ejemplo conveniencia",
)
