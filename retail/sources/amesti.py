from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_amesti_target = parse_shopify_target

AmestiStore = make_shopify_store(
    store_id="amesti",
    title="Amesti",
    site="www.amesti.cl",
    base="https://www.amesti.cl",
    category_help="Handle de colección Shopify",
)
